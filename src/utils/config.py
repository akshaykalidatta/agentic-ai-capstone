"""Config loading. Small on purpose: one place that knows where the repo root is."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

# src/utils/config.py -> src/utils -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@functools.lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"config file missing: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def app_config() -> dict[str, Any]:
    return load_yaml("app_config.yaml")


def routing_rules() -> dict[str, Any]:
    return load_yaml("routing_rules.yaml")


def resolve(relative: str) -> Path:
    """Turn a config path into an absolute one, so scripts work from any cwd."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p
