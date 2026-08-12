"""Shared test config.

Force a deterministic catalog for the whole suite: disable service
auto-detection *before arccode is imported* so tests run against the static
DEFAULT_MODELS regardless of what is connected on the machine (Ollama, keys).
"""
import os

# Must be set before any `import arccode.config`, which happens at test collection.
os.environ.setdefault("ARCCODE_NO_AUTODETECT", "1")
