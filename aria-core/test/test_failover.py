import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch
import requests

# Add the parent directory to sys.path so we can import router
parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

import router
import memory_store

# Original requests.post
_orig_post = requests.post

def _mock_post(url, *args, **kwargs):
    if "generativelanguage.googleapis.com" in url or "api.groq.com" in url:
        raise requests.exceptions.Timeout("Simulated timeout for testing failover.")
    return _orig_post(url, *args, **kwargs)

async def test_circuit_breaker():
    print("\n--- Starting Circuit Breaker Failover Test ---")
    
    print("Resetting circuit breaker state in memory_store...")
    for engine in ["API1", "API2", "GROQ", "OPENROUTER", "LOCAL"]:
        memory_store.update_engine_metric(engine, tokens=0, status=200, latency=0.0, failures=0, cooldown=0.0)
        
    print("Simulating timeouts for API1, API2, and GROQ.")
    print("Expected failover chain: API1 (fail) -> API2 (fail) -> GROQ (fail) -> OPENROUTER (success)")
    
    # We use a patch to force timeouts
    with patch("requests.post", side_effect=_mock_post):
        try:
            response = await router.generate("Reply with exactly the word 'SUCCESS'.")
            print("\nFinal Response received:")
            print(response)
            
            # Verify memory_store state
            print("\n--- Engine Metrics State ---")
            for engine in ["API1", "API2", "GROQ", "OPENROUTER", "LOCAL"]:
                metric = memory_store.get_engine_metric(engine)
                if metric:
                    print(f"{engine}: failures={metric.get('consecutive_failures', 0)}, status={metric.get('status', 'unknown')}")
                else:
                    print(f"{engine}: No metrics recorded.")
                    
        except Exception as e:
            print(f"\nTest Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_circuit_breaker())
