"""Embedding and vector-store interfaces, plus dependency-free default implementations.

Swap `HashEmbedder` for sentence-transformers and `InMemoryVectorStore` for Chroma/pgvector
later; nothing else changes as long as they match these shapes.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

Vector = Sequence[float]


def cosine(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Bag-of-words hashed into a fixed-size vector. Crude but deterministic and offline."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            out.append(v)
        return out


class VectorStore(Protocol):
    def upsert(self, record_id: str, embedding: Vector) -> None: ...
    def delete(self, record_id: str) -> None: ...
    def search(self, embedding: Vector, candidates: Sequence[str]) -> list[tuple[str, float]]:
        """Score `candidates` (already filtered by the caller) by similarity, best first."""
        ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def upsert(self, record_id: str, embedding: Vector) -> None:
        self._vectors[record_id] = list(embedding)

    def delete(self, record_id: str) -> None:
        self._vectors.pop(record_id, None)

    def search(self, embedding: Vector, candidates: Sequence[str]) -> list[tuple[str, float]]:
        scored = [(rid, cosine(embedding, self._vectors[rid])) for rid in candidates if rid in self._vectors]
        return sorted(scored, key=lambda x: x[1], reverse=True)
