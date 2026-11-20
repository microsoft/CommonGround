"""
AI client and utilities for puzzle task.
Handles Azure OpenAI integration and chat completion requests.
"""
import atexit
import logging
import threading
from typing import List, Dict, Any, Optional

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, AsyncOpenAI, BadRequestError
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

# Reply budget for reasoning models when MAX_TOKENS is not set. They spend part of the
# budget on hidden reasoning before any visible text, so the classic 1500 can run out first.
REASONING_MAX_TOKENS = 16000


class AIClient:
    """Manages Azure OpenAI client and chat completions."""
    
    def __init__(self):
        self.deployment = settings.OPENAI_GPT4_DEPLOYMENT
        self.client = self._initialize_client()
        # Newer reasoning models reject 'max_tokens' and any non-default temperature.
        # Requests start with the classic parameters and switch once if the model refuses them.
        self.token_parameter = 'max_tokens'
        self.send_temperature = True
        self.last_budget: Optional[int] = None

    @property
    def is_reasoning_model(self) -> bool:
        return self.token_parameter == 'max_completion_tokens'

    def reply_budget(self, requested: Optional[int]) -> int:
        """The token limit to send: MAX_TOKENS if set, otherwise sized for the kind of model."""
        budget = requested or settings.MAX_TOKENS_DEFAULT
        if self.is_reasoning_model and not getattr(settings, 'MAX_TOKENS_SET', False):
            budget = max(budget, REASONING_MAX_TOKENS)
        return budget

    def describe_settings(self) -> Dict[str, Any]:
        """How requests are actually sent, for the run logs."""
        return {
            'token_parameter': self.token_parameter,
            'max_tokens': self.last_budget or self.reply_budget(None),
            'temperature': 0.0 if self.send_temperature else 'model default',
            'reasoning_model': self.is_reasoning_model,
        }
    
    def _initialize_client(self):
        """Initialize the OpenAI client.

        Auth precedence (an explicit scope selects Entra ID instead of API keys):
        1. OPENAI_API_KEY without OPENAI_ENDPOINT -> standard OpenAI (api.openai.com)
        2. OPENAI_ENDPOINT + OPENAI_SCOPE         -> Azure OpenAI via Azure CLI (local az login)
        3. OPENAI_ENDPOINT + OPENAI_API_KEY       -> Azure OpenAI via API key
        4. OPENAI_ENDPOINT only                   -> Azure OpenAI via Azure CLI (default scope)
        """
        api_key = getattr(settings, 'OPENAI_API_KEY', '') or ''
        endpoint = settings.OPENAI_ENDPOINT or ''
        scope = settings.OPENAI_SCOPE or ''
        try:
            if api_key and not endpoint:
                client = AsyncOpenAI(api_key=api_key)
                logger.info("OpenAI client initialized (API key)")
            elif endpoint and scope:
                token_provider = get_bearer_token_provider(AzureCliCredential(), scope)
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    azure_ad_token_provider=token_provider,
                )
                logger.info("Azure OpenAI client initialized (Entra ID, Azure CLI)")
            elif endpoint and api_key:
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    api_key=api_key,
                )
                logger.info("Azure OpenAI client initialized (API key)")
            elif endpoint:
                default_scope = scope or "https://cognitiveservices.azure.com/.default"
                token_provider = get_bearer_token_provider(AzureCliCredential(), default_scope)
                client = AsyncAzureOpenAI(
                    azure_endpoint=endpoint,
                    api_version=settings.OPENAI_API_VERSION,
                    azure_ad_token_provider=token_provider,
                )
                logger.info("Azure OpenAI client initialized (Entra ID, Azure CLI, default scope)")
            else:
                raise RuntimeError(
                    "No AI backend configured: set OPENAI_API_KEY, or OPENAI_ENDPOINT "
                    "with OPENAI_SCOPE (Entra ID) or OPENAI_API_KEY."
                )
            return client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
    
    def _adapt_to_rejected_parameter(self, error: BadRequestError) -> bool:
        """Switch to what the model accepts after a 400 about a parameter; True to retry."""
        body = error.body if isinstance(error.body, dict) else {}
        body = body.get('error', body) if isinstance(body.get('error'), dict) else body
        param = body.get('param')
        if param == 'max_tokens' and self.token_parameter == 'max_tokens':
            self.token_parameter = 'max_completion_tokens'
            logger.warning("Model %s does not accept 'max_tokens'; using 'max_completion_tokens' from now on",
                           self.deployment)
            return True
        if param == 'temperature' and self.send_temperature:
            self.send_temperature = False
            logger.warning("Model %s only supports its default temperature; temperature is no longer sent, "
                           "so its replies are not deterministic", self.deployment)
            return True
        return False

    async def get_chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        max_tokens: int = None,
        temperature: float = 0.0
    ) -> str:
        """Get chat completion from Azure OpenAI."""
        while True:
            budget = self.reply_budget(max_tokens)
            request = {
                'model': self.deployment,
                'messages': messages,
                self.token_parameter: budget,
            }
            if self.send_temperature:
                request['temperature'] = temperature
            try:
                response = await self.client.chat.completions.create(**request)
            except BadRequestError as e:
                if self._adapt_to_rejected_parameter(e):
                    continue
                logger.error(f"Error in chat completion: {e}")
                raise
            except Exception as e:
                logger.error(f"Error in chat completion: {e}")
                raise
            self.last_budget = budget

            choice = response.choices[0]
            content = choice.message.content
            if not content:
                # Reasoning models spend part of the token budget on hidden reasoning,
                # so a tight budget can end before any visible reply is written.
                raise RuntimeError(
                    f"The model returned no text (finish_reason={choice.finish_reason}). "
                    f"If it is 'length', the {budget}-token budget ran out; set a higher MAX_TOKENS in .env.")
            logger.info(f"Successfully generated completion with {len(content)} characters")
            return content
    
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
