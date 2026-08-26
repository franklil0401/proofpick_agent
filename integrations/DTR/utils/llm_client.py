"""
DTR Framework - LLM Client

Universal LLM client supporting multiple providers (OpenAI, Azure, DeepSeek, etc.)
with retry logic and rate limit handling.
"""

import os
import time
import json
import re
import random
import requests
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from openai import OpenAI, AzureOpenAI
except ImportError:
    OpenAI = None
    AzureOpenAI = None

try:
    from dotenv import load_dotenv
    # Try to load from config directory (try both .env and env.env)
    env_file = Path(__file__).parent.parent / "config" / "env.env"
    if not env_file.exists():
        env_file = Path(__file__).parent.parent / "config" / ".env"
    
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()  # Load from current directory or system
except ImportError:
    pass  # dotenv not available

from .logger import logger


class LLMClient:
    """
    Universal LLM client with retry logic and multiple provider support
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: str = "openai",
        max_retries: int = 5,
        initial_retry_delay: float = 1.0,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None
    ):
        """
        Initialize LLM client
        
        Args:
            model: Model name (e.g., "gpt-4", "deepseek-v3")
            base_url: API base URL
            api_key: API key
            provider: Provider type ("openai", "azure", "deepseek")
            max_retries: Maximum retry attempts
            initial_retry_delay: Initial delay between retries
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
        """
        # Load from environment if not provided
        self.model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.provider = provider.lower()
        
        # Configuration
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Call statistics
        self.call_count = 0
        self.total_output_tokens = 0
        self.total_input_tokens = 0
        
        # Check if authentication is needed
        self.requires_auth = not ('ti.tencentcs.com' in self.base_url or 
                                   'ms-' in self.model.lower())
        
        if not self.api_key and self.requires_auth:
            logger.warning("No API key provided - some providers may fail")
        
        # Initialize client
        self._init_client()
        
        logger.info(f"LLM Client initialized: {self.provider}/{self.model}")
    
    def reset_call_count(self):
        """重置调用计数"""
        self.call_count = 0
        self.total_output_tokens = 0
        self.total_input_tokens = 0
    
    def get_call_count(self) -> int:
        """获取调用次数"""
        return self.call_count
    
    def get_token_stats(self) -> dict:
        """获取token统计"""
        return {
            'output_tokens': self.total_output_tokens,
            'input_tokens': self.total_input_tokens,
            'total_tokens': self.total_output_tokens + self.total_input_tokens
        }
    
    def _init_client(self):
        """Initialize the appropriate client based on provider"""
        if OpenAI is None or AzureOpenAI is None:
            self.client = None
            logger.info("OpenAI library not available, using requests fallback")
            return
        
        try:
            if self.provider == "azure":
                api_version = os.getenv("API_VERSION", "2024-02-15-preview")
                self.client = AzureOpenAI(
                    azure_endpoint=self.base_url,
                    api_key=self.api_key,
                    api_version=api_version
                )
            else:
                self.client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key
                )
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}, using requests")
            self.client = None
    
    def call_api(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Call LLM API with retry logic
        
        Args:
            prompt: Input prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens
            **kwargs: Additional parameters
            
        Returns:
            Generated text response
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        for attempt in range(self.max_retries + 1):
            try:
                # Check if special model type
                is_special = ('utuv1' in self.model.lower() or 
                             'qwen' in self.model.lower() or
                             'ms-' in self.model.lower() or
                             'ti.tencentcs.com' in self.base_url)
                
                if is_special:
                    response = self._call_special_api(prompt, temp, tokens, **kwargs)
                elif self.client is not None:
                    response = self._call_openai_api(prompt, temp, tokens, **kwargs)
                else:
                    response = self._call_requests_api(prompt, temp, tokens, **kwargs)
                
                # Increment call counter
                self.call_count += 1
                
                # Record tokens if available (response is a tuple: (content, usage))
                if isinstance(response, tuple) and len(response) == 2:
                    content, usage = response
                    if usage:
                        self.total_output_tokens += usage.get('completion_tokens', 0)
                        self.total_input_tokens += usage.get('prompt_tokens', 0)
                    return self._clean_response(content)
                
                # Clean and return response
                return self._clean_response(response)
                
            except Exception as e:
                error_msg = str(e).lower()
                is_rate_limit = any(kw in error_msg for kw in [
                    'rate limit', 'rate_limit', '429', 'too many requests',
                    'quota', 'throttle', 'concurrent'
                ])
                
                if attempt < self.max_retries:
                    # Exponential backoff with jitter
                    delay = self.initial_retry_delay * (2 ** attempt)
                    jitter = random.uniform(0, delay * 0.5)
                    total_delay = delay + jitter
                    
                    if is_rate_limit:
                        total_delay = max(total_delay, 5.0 + random.uniform(0, 3.0))
                        logger.warning(
                            f"Rate limit hit, retrying in {total_delay:.1f}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                    else:
                        logger.warning(
                            f"API call failed: {e}, retrying in {total_delay:.1f}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                    
                    time.sleep(total_delay)
                else:
                    logger.error(f"LLM API call failed after {self.max_retries} retries: {e}")
                    raise
    
    def _call_openai_api(
        self,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> str:
        """Call using OpenAI client library"""
        params = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature
        }
        
        if max_tokens:
            params["max_tokens"] = max_tokens
        
        params.update(kwargs)
        
        completion = self.client.chat.completions.create(**params)
        content = completion.choices[0].message.content or ""
        usage = {
            'completion_tokens': completion.usage.completion_tokens if completion.usage else 0,
            'prompt_tokens': completion.usage.prompt_tokens if completion.usage else 0,
            'total_tokens': completion.usage.total_tokens if completion.usage else 0
        } if hasattr(completion, 'usage') and completion.usage else None
        return (content, usage)
    
    def _call_special_api(
        self,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> str:
        """Call special models (Tencent hosted, etc.) with specific parameters"""
        url = f"{self.base_url}/chat/completions"
        
        # Configure based on model type
        if 'qwen' in self.model.lower():
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens or 8000,
                "stream": False
            }
        elif 'ms-' in self.model.lower():
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens or 8000,
                "stream": False
            }
        else:  # utuv1, etc.
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.6,
                "max_tokens": max_tokens or 32768,
                "top_p": 0.95,
                "top_k": 20,
                "presence_penalty": 1.5,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False}
            }
        
        payload.update(kwargs)
        
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"] or ""
            usage = result.get('usage')
            return (content, usage)
        else:
            raise Exception(f"API request failed ({response.status_code}): {response.text}")
    
    def _call_requests_api(
        self,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> str:
        """Fallback using requests library"""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        payload.update(kwargs)
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"] or ""
            usage = result.get('usage')
            return (content, usage)
        else:
            raise Exception(f"API request failed ({response.status_code}): {response.text}")
    
    def _clean_response(self, text: str) -> str:
        """Clean LLM response text"""
        if not isinstance(text, str):
            return ""
        
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        
        # Remove zero-width characters
        text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
        
        # Remove empty thinking tags
        text = re.sub(r"<think>\s*</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*<think>([\s\S]*?)</think>\s*", r"\1", text, flags=re.IGNORECASE)
        text = text.strip()

        # if "```json" in text:
        #     text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        #     pass
        # elif "```python" in text:
        #     text = text.split("```python", 1)[1].split("```", 1)[0].strip()
        #     pass
        
        # # Extract JSON if present
        # if "{" in text:
        #     start = text.find("{")
        #     brace = 0
        #     end = -1
        #     for i in range(start, len(text)):
        #         if text[i] == "{":
        #             brace += 1
        #         elif text[i] == "}":
        #             brace -= 1
        #             if brace == 0:
        #                 end = i
        #                 break
        #     if end != -1:
        #         candidate = text[start:end + 1].strip()
        #         if candidate.startswith("{") and candidate.endswith("}"):
        #             text = candidate
        
        # # Remove markdown code fences
        # fence_pattern = r"^\s*```(?:\s*\w+)?\s*\n(?P<body>[\s\S]*?)\n\s*```\s*$"
        # match = re.match(fence_pattern, text, re.MULTILINE)
        # if match:
        #     text = match.group("body").strip()
        # else:
        #     if text.startswith("```") and text.endswith("```") and len(text) >= 6:
        #         text = text[3:-3].strip()
        
        # # Remove "json" prefix
        # if text.lower().startswith("json\n"):
        #     text = text.split("\n", 1)[1].strip()
        
        return text


# Convenience function
def create_llm_client(**kwargs) -> LLMClient:
    """Create LLM client with given parameters"""
    return LLMClient(**kwargs)


if __name__ == "__main__":
    # Test client (mock mode - will fail without real API key)
    client = LLMClient(model="gpt-3.5-turbo")
    print("LLM Client created successfully")
    print(f"Model: {client.model}")
    print(f"Provider: {client.provider}")

