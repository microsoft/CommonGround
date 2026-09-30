"""
AI client and utilities for puzzle task.
Handles Azure OpenAI integration and chat completion requests.
"""
import atexit
import logging
import threading
from typing import List, Dict, Any, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, AsyncOpenAI
from .async_executor import get_async_executor

try:
    from ..utils import settings
except ImportError:
    # Fallback for direct module usage
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils import settings


logger = logging.getLogger(__name__)


class AIClient:
    """Manages Azure OpenAI client and chat completions."""
    
    def __init__(self):
        self.client = self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the OpenAI client.

        Auth precedence (Entra ID wins when a scope is set, e.g. TRAPI, since such
        gateways authenticate with AD tokens and reject API keys):
        1. OPENAI_API_KEY without OPENAI_ENDPOINT -> standard OpenAI (api.openai.com)
        2. OPENAI_ENDPOINT + OPENAI_SCOPE         -> Azure OpenAI via Entra ID (az login / managed identity)
        3. OPENAI_ENDPOINT + OPENAI_API_KEY       -> Azure OpenAI via API key
        4. OPENAI_ENDPOINT only                   -> Azure OpenAI via Entra ID (default scope)
        """
        api_key = getattr(settings, 'OPENAI_API_KEY', '') or ''
        endpoint = settings.OPENAI_ENDPOINT or ''
        scope = settings.OPENAI_SCOPE or ''
        try:
            if api_key and not endpoint:
                client = AsyncOpenAI(api_key=api_key)
                logger.info("OpenAI client initialized (API key)")
            elif endpoint and scope:
                token_provider = get_bearer_token_provider(DefaultAzureCredential(), scope)
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    azure_ad_token_provider=token_provider,
                )
                logger.info("Azure OpenAI client initialized (Entra ID)")
            elif endpoint and api_key:
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    api_key=api_key,
                )
                logger.info("Azure OpenAI client initialized (API key)")
            elif endpoint:
                default_scope = scope or "https://cognitiveservices.azure.com/.default"
                token_provider = get_bearer_token_provider(DefaultAzureCredential(), default_scope)
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    azure_ad_token_provider=token_provider,
                )
                logger.info("Azure OpenAI client initialized (Entra ID, default scope)")
            else:
                raise RuntimeError(
                    "No AI backend configured: set OPENAI_API_KEY, or OPENAI_ENDPOINT "
                    "with OPENAI_SCOPE (Entra ID) or OPENAI_API_KEY."
                )
            return client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
    
    async def get_chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        max_tokens: int = None,
        temperature: float = 0.0
    ) -> str:
        """Get chat completion from Azure OpenAI."""
        max_tokens = max_tokens or settings.MAX_TOKENS_DEFAULT
        
        try:
            response = await self.client.chat.completions.create(
                model=settings.OPENAI_GPT4_DEPLOYMENT,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            content = response.choices[0].message.content
            logger.info(f"Successfully generated completion with {len(content)} characters")
            return content
            
        except Exception as e:
            logger.error(f"Error in chat completion: {e}")
            raise
    
    def get_chat_completion_sync(
        self, 
        messages: List[Dict[str, str]], 
        max_tokens: int = None
    ) -> str:
        """Synchronous wrapper for get_chat_completion."""
        try:
            return get_async_executor().run_async(self.get_chat_completion(messages, max_tokens))
        except Exception as e:
            logger.error(f"Error in synchronous chat completion: {e}")
            return f"GENERATION ERROR: {str(e)}"


# Global AI client instance
ai_client = None
_client_lock = threading.Lock()

def get_ai_client() -> AIClient:
    """Get or create global AI client instance."""
    global ai_client
    with _client_lock:
        if ai_client is None:
            ai_client = AIClient()
        return ai_client


def _close_cached_client() -> None:
    global ai_client
    executor = get_async_executor()
    with _client_lock:
        if ai_client is not None and executor.is_running:
            executor.run_async(ai_client.client.close(), timeout=5.0)
            ai_client = None


# Registered after the executor so the transport closes before its event loop.
atexit.register(_close_cached_client)
