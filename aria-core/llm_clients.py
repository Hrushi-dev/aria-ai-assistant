import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

class ClientResponse:
    def __init__(self, text: str, status_code: int = 200, error: str = None):
        self.text = text
        self.status_code = status_code
        self.error = error

class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-pro"):
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, history: list = None) -> ClientResponse:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        contents = []
        if history:
            for msg in history:
                contents.append({
                    "role": msg.get("role", "user"),
                    "parts": [{"text": msg.get("content", "")}]
                })
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1
            }
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=20.0)
            if resp.status_code != 200:
                return ClientResponse("", status_code=resp.status_code, error=resp.text)
            
            data = resp.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return ClientResponse(text)
            except (KeyError, IndexError):
                return ClientResponse("", status_code=500, error="Invalid response format from Gemini")
        except requests.exceptions.Timeout:
            return ClientResponse("", status_code=504, error="Timeout")
        except requests.exceptions.RequestException as e:
            return ClientResponse("", status_code=500, error=str(e))

class OpenRouterClient:
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-pro"):
        self.api_key = api_key
        self.model = model
        
    def generate(self, prompt: str, history: list = None) -> ClientResponse:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = history or []
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=45.0)
            if resp.status_code != 200:
                return ClientResponse("", status_code=resp.status_code, error=resp.text)
                
            data = resp.json()
            try:
                text = data["choices"][0]["message"]["content"]
                return ClientResponse(text)
            except (KeyError, IndexError):
                return ClientResponse("", status_code=500, error="Invalid response format from OpenRouter")
        except requests.exceptions.Timeout:
            return ClientResponse("", status_code=504, error="Timeout")
        except requests.exceptions.RequestException as e:
            return ClientResponse("", status_code=500, error=str(e))

class OllamaClient:
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = model
        
    def generate(self, prompt: str, history: list = None) -> ClientResponse:
        url_chat = "http://localhost:11434/api/chat"
        messages = history or []
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": 4096,
                "temperature": 0.0
            }
        }
        
        try:
            resp = requests.post(url_chat, json=payload, timeout=45.0)
            if resp.status_code != 200:
                return ClientResponse("", status_code=resp.status_code, error=resp.text)
                
            data = resp.json()
            try:
                text = data["message"]["content"]
                return ClientResponse(text)
            except KeyError:
                return ClientResponse("", status_code=500, error="Invalid response format from Ollama")
        except requests.exceptions.Timeout:
            return ClientResponse("", status_code=504, error="Timeout")
        except requests.exceptions.RequestException as e:
            return ClientResponse("", status_code=500, error=str(e))
