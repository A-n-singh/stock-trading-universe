"""Rough notebook for one worker task. Thrown away when the task ends; never shared."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scratchpad:
    task: str
    max_note_chars: int = 1500
    notes: list[str] = field(default_factory=list)

    def add(self, note: str) -> None:
        if len(note) > self.max_note_chars:
            note = note[: self.max_note_chars] + " …[truncated]"
        self.notes.append(note)

    def render(self) -> str:
        return "\n".join(f"{i + 1}. {n}" for i, n in enumerate(self.notes))

    def clear(self) -> None:
        self.notes.clear()
