"""Training steps for the in-house decision model (TDD §Model Training Approach).

  1. SFT   - supervised fine-tuning on context -> {answer, confidence} pairs (LoRA adapters)
  2. RL    - GRPO with a reward for real profit plus honest confidence (calibration)
  3. merge - fold the LoRA adapters into the weights and save; quantize for fast serving

Base model: start small to prove the pipeline (Qwen/Qwen2.5-1.5B-Instruct fits a free Colab GPU),
then scale to the ~30-40B range on a rented GPU (e.g. Qwen2.5-32B-Instruct with 4-bit QLoRA).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .calibration import reward as calibration_reward
from .models import parse_output
from .schema import GATE_QUESTIONS

ALLOWED = GATE_QUESTIONS["trade"].allowed_answers


def load_rows(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _dataset(rows: list[dict]):
    from datasets import Dataset

    return Dataset.from_list(rows)


@dataclass
class TrainConfig:
    base_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    output_dir: str = "models/decision-sft"
    epochs: float = 2.0
    batch_size: int = 8
    learning_rate: float = 2e-4
    max_length: int = 1024
    lora_r: int = 16
    lora_alpha: int = 32
    load_in_4bit: bool = False  # QLoRA for 30-40B models on one GPU (needs bitsandbytes + CUDA)
    max_steps: int = -1
    bf16: bool = False


def _lora(cfg: TrainConfig):
    from peft import LoraConfig

    return LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")


def _model_kwargs(cfg: TrainConfig) -> dict:
    if not cfg.load_in_4bit:
        return {}
    import torch
    from transformers import BitsAndBytesConfig

    return {"quantization_config": BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                      bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)}


def sft(train_jsonl: str | Path, cfg: TrainConfig) -> str:
    """Step 1: teach the input -> output pattern. Loss only on the answer, not the prompt."""
    from trl import SFTConfig, SFTTrainer

    rows = [{"prompt": r["prompt"], "completion": r["completion"]} for r in load_rows(train_jsonl)]
    args = SFTConfig(
        output_dir=cfg.output_dir, num_train_epochs=cfg.epochs, per_device_train_batch_size=cfg.batch_size,
        learning_rate=cfg.learning_rate, max_length=cfg.max_length, completion_only_loss=True, logging_steps=10,
        save_strategy="no", report_to="none", max_steps=cfg.max_steps, bf16=cfg.bf16,
        model_init_kwargs=_model_kwargs(cfg) or None,
    )
    trainer = SFTTrainer(model=cfg.base_model, args=args, train_dataset=_dataset(rows), peft_config=_lora(cfg))
    trainer.train()
    trainer.save_model(cfg.output_dir)
    return cfg.output_dir


def profit_and_calibration_reward(completions, label, pnl_r, taken_action, **_) -> list[float]:
    """GRPO reward: realised profit of the chosen answer (in R) plus a Brier-style calibration term.
    Unparseable answers get the worst score, so the model learns to always answer in the format."""
    out = []
    for comp, lab, pnl, taken in zip(completions, label, pnl_r, taken_action):
        text = comp[0]["content"] if isinstance(comp, list) else str(comp)
        parsed, ok = parse_output(text, ALLOWED)
        if not ok:
            out.append(-2.0)
            continue
        if parsed.answer == taken:
            realised = pnl
        elif parsed.answer == "hold":
            realised = 0.0
        else:
            realised = -abs(pnl)  # unknown counterfactual: scored pessimistically
        out.append(calibration_reward(realised, 1.0, parsed.confidence, parsed.answer == lab))
    return out


def rl(train_jsonl: str | Path, start_from: str, cfg: TrainConfig, num_generations: int = 4) -> str:
    """Step 2: GRPO on top of the SFT model, rewarding decisions that made money and honest confidence."""
    from trl import GRPOConfig, GRPOTrainer

    rows = [{k: r[k] for k in ("prompt", "label", "pnl_r", "taken_action")} for r in load_rows(train_jsonl)]
    args = GRPOConfig(
        output_dir=cfg.output_dir, num_train_epochs=cfg.epochs, per_device_train_batch_size=max(cfg.batch_size, num_generations),
        learning_rate=cfg.learning_rate / 20, num_generations=num_generations, max_completion_length=48,
        logging_steps=5, save_strategy="no", report_to="none", max_steps=cfg.max_steps, bf16=cfg.bf16,
    )
    trainer = GRPOTrainer(model=start_from, reward_funcs=profit_and_calibration_reward, args=args,
                          train_dataset=_dataset(rows), peft_config=_lora(cfg))
    trainer.train()
    trainer.save_model(cfg.output_dir)
    return cfg.output_dir


def merge(adapter_dir: str, out_dir: str) -> str:
    """Fold LoRA adapters into the base weights so the model loads and serves like a normal model."""
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    model = AutoPeftModelForCausalLM.from_pretrained(adapter_dir)
    model = model.merge_and_unload()
    model.save_pretrained(out_dir)
    AutoTokenizer.from_pretrained(adapter_dir).save_pretrained(out_dir)
    return out_dir


QUANTIZE_HELP = """Quantize the merged model for fast, cheap inference (pick one):
  GPU serving (vLLM, AWQ 4-bit):   pip install llmcompressor  ->  oneshot(model=MERGED, recipe=AWQModifier(scheme="W4A16"))
                                   then: vllm serve MERGED-AWQ   and point HTTPDecisionModel at /v1/chat/completions
  CPU / laptop (llama.cpp GGUF):   python llama.cpp/convert_hf_to_gguf.py MERGED --outfile model.gguf
                                   ./llama-quantize model.gguf model-Q4_K_M.gguf Q4_K_M ; ./llama-server -m model-Q4_K_M.gguf
Both expose a chat-completions endpoint that HTTPDecisionModel can call."""
