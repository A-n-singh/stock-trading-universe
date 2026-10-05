"""Connection to a language model for the research agents, returning schema-checked JSON.

The research loop is slow and careful by design (SDD), so it can afford a strong model.

Google Gemini (used for now):
  GEMINI_API_KEY      free key from aistudio.google.com
  TU_GEMINI_MODEL     default gemini-2.5-flash

Claude (the original plan, once the card works):
  ANTHROPIC_API_KEY   credentials (or an `ant auth login` profile)
  TU_LLM_MODEL        model id, default claude-opus-5
  TU_LLM_EFFORT       low | medium | high (default low: scoring a headline is a simple task)

Gemini is used when both keys are set. With neither, research uses keyword scoring.
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


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_EMBED_MODEL = "gemini-embedding-001"


class GeminiLLM:
    """Google Gemini through its chat-completions endpoint, with JSON output. The schema is given in
    the prompt and checked here."""

    def __init__(self, api_key: str, model: str | None = None, timeout: float = 60.0, opener: Any = None) -> None:
        self.base_url = GEMINI_URL
        self.model = model or os.environ.get("TU_GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.api_key = api_key
        self.timeout = timeout
        self.name = f"gemini:{self.model}"
        self._open = opener  # for tests: (request, timeout) -> response with .read()

    def _post(self, path: str, body: dict) -> dict:
        import urllib.request

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/{path}", json.dumps(body).encode(), headers)
        with (self._open or urllib.request.urlopen)(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embedding vectors (Gemini's "fingerprints" for text), used to route news to team leads."""
        import urllib.error

        model = model or os.environ.get("TU_GEMINI_EMBED_MODEL", DEFAULT_GEMINI_EMBED_MODEL)
        try:
            data = self._post("embeddings", {"model": model, "input": list(texts)})
            return [list(map(float, d["embedding"])) for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except urllib.error.HTTPError as e:
            raise LLMUnavailable(f"API error {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMUnavailable("network error") from e
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise LLMUnavailable("unexpected embedding answer") from e

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        import urllib.error

        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{system}\n\nAnswer with one JSON object only, matching this JSON schema:\n{json.dumps(schema)}"},
                {"role": "user", "content": prompt},
            ],
        }
        def post(b: dict) -> dict:
            return self._post("chat/completions", b)

        try:
            try:
                data = post(body)
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                body.pop("response_format")  # retry without JSON mode; the prompt still asks for JSON
                data = post(body)
        except urllib.error.HTTPError as e:
            raise LLMUnavailable(f"API error {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMUnavailable("network error") from e
        except json.JSONDecodeError as e:
            raise LLMUnavailable("service did not return JSON") from e
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailable("unexpected answer shape") from e
        return check_schema(_json_from_text(text), schema)


class GeminiEmbedder:
    """Text -> vector with Gemini embeddings, remembered so the same text is never sent twice."""

    def __init__(self, llm: GeminiLLM, model: str | None = None) -> None:
        self.llm = llm
        self.model = model or os.environ.get("TU_GEMINI_EMBED_MODEL", DEFAULT_GEMINI_EMBED_MODEL)
        self.name = f"gemini:{self.model}"
        self._cache: dict[str, list[float]] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        for i in range(0, len(todo), 100):
            batch = todo[i:i + 100]
            for t, v in zip(batch, self.llm.embed(batch, self.model)):
                self._cache[t] = v
        if len(self._cache) > 20000:
            self._cache = dict(list(self._cache.items())[-10000:])
        return [self._cache[t] for t in texts]


def _json_from_text(text: str) -> dict[str, Any]:
    """Parse JSON, tolerating code fences or a thinking preamble around the object."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMUnavailable("answer was not valid JSON")


def check_schema(out: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Minimal check for the flat schemas used here: required keys, basic types, enums."""
    if not isinstance(out, dict):
        raise LLMUnavailable("answer was not a JSON object")
    types = {"string": str, "number": (int, float), "boolean": bool, "integer": int}
    for key in schema.get("required", []):
        if key not in out:
            raise LLMUnavailable(f"answer is missing '{key}'")
    for key, spec in schema.get("properties", {}).items():
        if key not in out:
            continue
        want = types.get(spec.get("type", ""))
        v = out[key]
        if want and (not isinstance(v, want) or (spec.get("type") == "number" and isinstance(v, bool))):
            raise LLMUnavailable(f"'{key}' has the wrong type")
        if "enum" in spec and v not in spec["enum"]:
            raise LLMUnavailable(f"'{key}' must be one of {spec['enum']}")
    return out


def default_llm() -> JSONLLM | None:
    """Gemini when GEMINI_API_KEY is set, else Claude when credentials exist, otherwise None (keywords)."""
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiLLM(os.environ["GEMINI_API_KEY"])
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")):
        return None
    try:
        return ClaudeLLM()
    except Exception as e:  # SDK missing or misconfigured
        log.warning("Claude unavailable, using rule-based scoring: %s", e)
        return None
