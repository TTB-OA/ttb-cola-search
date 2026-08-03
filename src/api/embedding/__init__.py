"""Pluggable image/text embedding providers.

Import :func:`get_embedder` to obtain the configured provider instance. Add a
new provider by dropping a module in ``providers/`` and registering it in
``registry.py`` — no other code needs to change.
"""
from .base import Embedder
from .registry import available_providers, get_embedder

__all__ = ["Embedder", "available_providers", "get_embedder"]
