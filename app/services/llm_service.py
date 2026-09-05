"""LLM service with retry logic and fallback responses."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.utils.llm import LLMConfig, LLMProvider, llm_call

logger = logging.getLogger(__name__)


class LLMService:
    """LLM service with retry logic and fallback responses.

    Provides two modes of resilience:
    - call_with_retry: Retries the call on transient failures.
    - call_with_fallback: Returns a caller-provided fallback string
      instead of raising on repeated failure.
    """

    def __init__(self, max_retries: int = 2, retry_delay: float = 1.0):
        """Initialize the LLM service.

        Args:
            max_retries: Maximum number of retry attempts (default 2).
            retry_delay: Delay in seconds between retries (default 1.0).
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def call_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        config: Optional[LLMConfig] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Call LLM with automatic retry on failure.

        Uses exponential backoff for retry delays. Raises the last
        exception if all attempts fail.

        Args:
            system_prompt: System-level instruction prompt.
            user_prompt: User message prompt.
            config: Optional LLM configuration.
            tools: Optional list of tool schemas.

        Returns:
            The LLM response text.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 2):
            try:
                return await llm_call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    config=config,
                    tools=tools,
                )
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
                if attempt <= self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"LLM call failed after {self.max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    async def call_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback_response: str,
        config: Optional[LLMConfig] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Call LLM, returning fallback on failure instead of raising.

        Args:
            system_prompt: System-level instruction prompt.
            user_prompt: User message prompt.
            fallback_response: String to return if all attempts fail.
            config: Optional LLM configuration.
            tools: Optional list of tool schemas.

        Returns:
            LLM response text, or fallback_response on failure.
        """
        try:
            return await self.call_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                config=config,
                tools=tools,
            )
        except Exception as exc:
            logger.error(
                "LLM call failed, returning fallback: %s",
                exc,
            )
            return fallback_response
