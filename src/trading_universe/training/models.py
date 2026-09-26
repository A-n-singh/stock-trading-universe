"""Decision models: the trained in-house model (local weights or a served endpoint) and simple baselines.

All implement `decide(example) -> Output`, so the retraining pipeline can compare any two of them
(e.g. the new model vs the live one, or vs an external paid service).
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .schema import Output, TrainingExample

_JSON = re.compile(r"\{.*?\}", re.S)


def parse_output(text: str, allowed: tuple[str, ...], default: str = "hold") -> tuple[Output, bool]:
    """Pull {"answer", "confidence"} out of model text. Returns (output, was_valid).
    Anything unparseable becomes the safe default with low confidence."""
    for m in _JSON.finditer(text or ""):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        ans, conf = d.get("answer"), d.get("confidence")
        if ans in allowed and isinstance(conf, (int, float)):
            return Output(ans, max(0.0, min(1.0, float(conf)))), True
    return Output(default if default in allowed else allowed[-1], 0.0), False


@dataclass
class ConstantModel:
    """Baseline: always the same answer (e.g. "always buy when the rules fire", or "never trade")."""

    answer: str
    confidence: float = 0.6
    model_id: str = ""

    def __post_init__(self) -> None:
        self.model_id = self.model_id or f"always-{self.answer}"

    def decide(self, example: TrainingExample) -> Output:
        return Output(self.answer, self.confidence)


@dataclass
class HFDecisionModel:
    """A model saved with transformers (e.g. after SFT/RL), run locally. Greedy, short answers."""

    path: str
    model_id: str = ""
    max_new_tokens: int = 48
    _tok: Any = field(default=None, repr=False)
    _model: Any = field(default=None, repr=False)
    invalid: int = 0

    def __post_init__(self) -> None:
        self.model_id = self.model_id or self.path

    def _load(self) -> None:
        if self._model is None:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(self.path)
            self._model = AutoModelForCausalLM.from_pretrained(self.path)
            self._model.eval()

    def generate(self, messages: list[dict]) -> str:
        import torch

        self._load()
        if getattr(self._tok, "chat_template", None):
            text = self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            text = "\n".join(m["content"] for m in messages) + "\n"
        inputs = self._tok(text, return_tensors="pt")
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False,
                                       pad_token_id=self._tok.pad_token_id or self._tok.eos_token_id)
        return self._tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    def decide(self, example: TrainingExample) -> Output:
        from .dataset import to_chat

        text = self.generate(to_chat(example)["prompt"])
        out, ok = parse_output(text, example.question.allowed_answers)
        self.invalid += not ok
        return out


@dataclass
class HTTPDecisionModel:
    """A model served over HTTP with a chat-completions API (e.g. the quantized in-house model on vLLM),
    or any external decision service with the same shape - used to compare against a paid provider."""

    url: str  # e.g. http://gpu-box:8000/v1/chat/completions
    model: str
    api_key: str = ""
    model_id: str = ""
    timeout: float = 10.0

    def __post_init__(self) -> None:
        self.model_id = self.model_id or f"http:{self.model}"

    def decide(self, example: TrainingExample) -> Output:
        from .dataset import to_chat

        body = json.dumps({"model": self.model, "messages": to_chat(example)["prompt"], "temperature": 0, "max_tokens": 64}).encode()
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, body, headers), timeout=self.timeout) as r:
                text = json.loads(r.read())["choices"][0]["message"]["content"]
        except Exception:
            return Output("hold", 0.0)  # unreachable model never causes a trade
        return parse_output(text, example.question.allowed_answers)[0]
