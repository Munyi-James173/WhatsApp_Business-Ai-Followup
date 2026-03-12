"""
src/config_loader.py
Loads and validates settings.yaml, exposing a singleton `cfg` object.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config/settings.yaml"))


class _AttrDict(dict):
    """Dict that allows attribute-style access for nested config."""
    def __getattr__(self, key: str) -> Any:
        try:
            val = self[key]
            if isinstance(val, dict):
                return _AttrDict(val)
            return val
        except KeyError:
            raise AttributeError(f"Config key '{key}' not found")

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        node = self
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


@lru_cache(maxsize=1)
def load_config() -> _AttrDict:
    if not CONFIG_PATH.exists():
        example = CONFIG_PATH.parent / "settings.example.yaml"
        raise FileNotFoundError(
            f"Config file not found at {CONFIG_PATH}. "
            f"Copy {example} to {CONFIG_PATH} and fill in your values."
        )
    with open(CONFIG_PATH) as fh:
        raw = yaml.safe_load(fh)
    return _AttrDict(raw)


# Convenient singleton
cfg = load_config()
