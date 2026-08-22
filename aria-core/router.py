import os
import time
import asyncio
from dotenv import load_dotenv
from llm_clients import GeminiClient, OpenRouterClient, OllamaClient, ClientResponse
import memory_store

load_dotenv()

COOLDOWN_SECONDS = 300  # 5 minutes

class RouterError(Exception):
    pass

def _get_engine_client(engine: str):
    if engine == "API1":
        key = os.getenv("GEMINI_API_KEY_1")
        if not key: return None
        return GeminiClient(key)
    elif engine == "API2":
        key = os.getenv("GEMINI_API_KEY_2")
        if not key: return None
        return GeminiClient(key)
    elif engine == "OPENROUTER":
        key = os.getenv("OPENROUTER_API_KEY")
        if not key: return None
        return OpenRouterClient(key)
    elif engine == "LOCAL":
        return OllamaClient()
    return None

def _prune_for_local(prompt: str, history: list):
    """Truncate/prune history and large embedded content to respect 4096 context window."""
    pruned_history = history[-4:] if history else []
    if len(prompt) > 8000:
        prompt = prompt[:7997] + "..."
    return prompt, pruned_history

async def generate(prompt: str, history: list = None, engine_override: str = None) -> str:
    """
    Tries API1 -> API2 -> OPENROUTER -> LOCAL in order unless engine_override is set.
    """
    engines_to_try = ["API1", "API2", "OPENROUTER", "LOCAL"]
    
    if engine_override:
        eng_upper = engine_override.upper()
        # Handle manual override values like "USE OPENROUTER" or just "OPENROUTER"
        for eng in engines_to_try:
            if eng in eng_upper:
                engines_to_try = [eng]
                break
            
    loop = asyncio.get_running_loop()
    
    for engine in engines_to_try:
        metric = memory_store.get_engine_metric(engine)
        if metric:
            cooldown_until = metric["cooldown_timestamp"]
            consecutive_failures = metric["consecutive_failures"]
        else:
            cooldown_until = 0.0
            consecutive_failures = 0
            
        if time.time() < cooldown_until:
            print(f"[Router] {engine} is in cooldown. Skipping.")
            continue
            
        client = _get_engine_client(engine)
        if not client:
            print(f"[Router] {engine} skipped (missing config/key).")
            continue
            
        current_prompt = prompt
        current_history = history or []
        
        if engine == "LOCAL":
            current_prompt, current_history = _prune_for_local(current_prompt, current_history)
            
        def _call_llm():
            start_time = time.time()
            resp = client.generate(current_prompt, current_history)
            lat = time.time() - start_time
            return resp, lat
            
        print(f"[Router] Attempting generation via {engine}...")
        resp, lat = await loop.run_in_executor(None, _call_llm)
        
        if resp.status_code == 200:
            memory_store.update_engine_metric(engine, tokens=0, status=200, latency=lat, failures=0, cooldown=0.0)
            return resp.text
            
        if resp.status_code == 400:
            memory_store.update_engine_metric(engine, tokens=0, status=400, latency=lat, failures=consecutive_failures, cooldown=cooldown_until)
            raise RouterError(f"400 Bad Request from {engine}: {resp.error}")
            
        print(f"[Router] {engine} failed with status {resp.status_code}: {resp.error}")
        consecutive_failures += 1
        if consecutive_failures >= 3:
            print(f"[Router] {engine} marked TEMPORARILY_DEAD (cooldown activated).")
            cooldown_until = time.time() + COOLDOWN_SECONDS
        
        memory_store.update_engine_metric(engine, tokens=0, status=resp.status_code, latency=lat, failures=consecutive_failures, cooldown=cooldown_until)
            
    raise RouterError("All available engines failed or are in cooldown.")
