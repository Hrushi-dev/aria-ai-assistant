import os
import time
import asyncio
from dotenv import load_dotenv
from llm_clients import GeminiClient, OpenRouterClient, OllamaClient, GroqClient, ClientResponse
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
    elif engine == "GROQ":
        key = os.getenv("GROQ_API_KEY")
        if not key: return None
        return GroqClient(key)
    elif engine == "LOCAL":
        return OllamaClient()
    return None

def _prune_for_local(prompt: str, history: list):
    """Truncate/prune history and large embedded content to respect 4096 context window."""
    pruned_history = history[-4:] if history else []
    if len(prompt) > 8000:
        prompt = prompt[:7997] + "..."
    return prompt, pruned_history

async def generate(prompt: str, history: list = None, image_path: str = None, engine_override: str = None) -> str:
    """
    Respects the user's active model mode and does NOT automatically fallback.
    If the model hits a rate limit or exhausts tokens, it throws a RouterError.
    """
    mode = engine_override
    if not mode:
        mode = memory_store.get_fact("active_model_mode") or "API1"
        
    mode = mode.upper()
    if mode == "CLOUD":
        engines_to_try = ["API1"]
    else:
        valid = ["API1", "API2", "GROQ", "OPENROUTER", "LOCAL"]
        engines_to_try = [eng for eng in valid if eng in mode]
        if not engines_to_try:
            engines_to_try = ["API1"]

    loop = asyncio.get_running_loop()
    engine = engines_to_try[0]
    client = _get_engine_client(engine)
    
    if not client:
        raise RouterError(f"Engine {engine} is missing config/key.")
        
    current_prompt = prompt
    current_history = history or []
    
    if engine == "LOCAL":
        current_prompt, current_history = _prune_for_local(current_prompt, current_history)
        
    def _call_llm():
        start_time = time.time()
        resp = client.generate(current_prompt, current_history, image_path)
        lat = time.time() - start_time
        return resp, lat
        
    print(f"[Router] Attempting generation via {engine}...")
    resp, lat = await loop.run_in_executor(None, _call_llm)
    
    if resp.status_code == 200:
        return resp.text
        
    if resp.status_code == 429 or "quota" in str(resp.error).lower() or "limit" in str(resp.error).lower():
        raise RouterError(f"Tokens/Quota exhausted for {engine}. Please ask me to switch to a different model (e.g., 'Change model to OPENROUTER' or 'LOCAL'). Details: {resp.error}")
        
    raise RouterError(f"Model {engine} failed (Status {resp.status_code}): {resp.error}")
