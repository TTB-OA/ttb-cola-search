"""Vector helpers for pgvector interop."""
from __future__ import annotations


def to_pgvector(vector: list[float]) -> str:
    """Format a Python float list as a pgvector text literal: ``[a,b,c]``."""
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"
