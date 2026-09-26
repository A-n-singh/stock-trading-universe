"""Connection to Claude for the research agents, returning schema-checked JSON.

The research loop is slow and careful by design (SDD), so it can afford a strong model.
Configure with environment variables:
  ANTHROPIC_API_KEY   credentials (or an `ant auth login` profile)
  TU_LLM_MODEL        model id, default claude-opus-5
  TU_LLM_EFFORT       low | medium | high (default low: scoring a headline is a simple task)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"


class JSONLLM(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class LLMUnavailable(RuntimeError):
    """No usable answer (no credentials, refusal, network). Callers fall back to rule-based scoring."""


class ClaudeLLM:
    def __init__(self, model: str | None = None, effort: str | None = None, client: Any = None, max_tokens: int = 4000) -> None:
        self.model = model or os.environ.get("TU_LLM_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("TU_LLM_EFFORT", "low")
        self.max_tokens = max_tokens
        self.name = f"claude:{self.model}"
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        import anthropic

        try:
            # Server-side refusal fallbacks are on by default: a declined request is re-run on a
            # fallback model inside the same call instead of simply stopping.
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("no valid Anthropic credentials") from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailable("rate limited") from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailable(f"API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable("network error") from e
        if response.stop_reason == "refusal":
            raise LLMUnavailable("request declined")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("answer cut off at max_tokens")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMUnavailable("answer was not valid JSON") from e


def default_llm() -> JSONLLM | None:
    """Claude when credentials exist, otherwise None (rule-based scoring is used)."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")):
        return None
    try:
        return ClaudeLLM()
    except Exception as e:  # SDK missing or misconfigured
        log.warning("Claude unavailable, using rule-based scoring: %s", e)
        return None
