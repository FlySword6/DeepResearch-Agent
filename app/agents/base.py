"""BaseAgent abstract class for all research agents."""

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAgent(ABC):
    """Abstract base class for all agents in the research system."""

    model_config = {"temperature": 0.3, "max_tokens": 4096}

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    async def invoke(
        self,
        state: Any,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Invoke the agent with current state and optional tools.

        Args:
            state: The current workflow state.
            tools: Optional list of tool schemas for function calling.

        Returns:
            A dictionary of updates to apply to the state.
        """
        raise NotImplementedError("Subclasses must implement invoke")

    @staticmethod
    def _parse_response(response: str) -> Dict[str, Any]:
        """
        Parse JSON from an LLM response string.

        Handles both pure JSON and markdown-fenced JSON blocks.
        """
        pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        match = re.search(pattern, response)

        if match:
            json_str = match.group(1).strip()
        else:
            json_str = response.strip()

        return json.loads(json_str)
