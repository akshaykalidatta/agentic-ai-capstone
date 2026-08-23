"""
Config loading. Small on purpose: one place that knows where the repo root is -- and, since
every entry point imports this module, the one place that can put `.env` into the environment
before anything reads it.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# src/utils/config.py -> src/utils -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

# Secrets live here and nowhere in config/. `.env` is gitignored; config/*.yaml is committed,
# so a key in a YAML file is a key one `git add config/` away from being public. `.env.example`
# is the committed half: it documents which names exist without holding a value.
ENV_FILE = REPO_ROOT / ".env"


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


def model_config() -> dict[str, Any]:
    return load_yaml("model_config.yaml")


def resolve(relative: str) -> Path:
    """Turn a config path into an absolute one, so scripts work from any cwd."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p


# ------------------------------------------------------------------------------ the .env file


def parse_env_file(text: str) -> dict[str, str]:
    """
    `KEY=value` lines to a dict. Blank lines and `#` comments skipped, an `export ` prefix
    allowed, one surrounding pair of quotes stripped, whitespace trimmed around both halves.

    Stdlib rather than `python-dotenv`, which happens to be installed here as somebody else's
    transitive dependency -- and a transitive dependency is not a contract. That is the same
    lesson the `langgraph-checkpoint-sqlite` pin taught: depend on what you declare. Fifteen
    lines is a cheaper thing to own than a version range to maintain.

    Deliberately *not* handled: inline `#` comments after an unquoted value, and multi-line
    values. An API key is opaque, so a `#` inside one has to survive; quote the value if it
    needs a trailing comment.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_file(path: Path | None = None, *, override: bool = False) -> list[str]:
    """
    Load `.env` into `os.environ`. Returns the names it set, for logging and for tests.

    `override=False` is the important half: a real environment variable always wins. Set one in
    the shell to try a second key for one run without editing the file, and -- more to the point
    -- a stale `.env` can never silently shadow what CI or a scheduled run injected.

    Missing file is a no-op, not an error: the deterministic paths (`--no-model`, `--gate`, the
    whole test suite) need no key at all, and demanding a secrets file to run them would be a
    new reason for a bare checkout to fail.
    """
    env_path = ENV_FILE if path is None else Path(path)
    if not env_path.is_file():
        return []

    applied = []
    for key, value in parse_env_file(env_path.read_text(encoding="utf-8")).items():
        if override or key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied


# At import, because every entry point -- `python -m src.main`, `streamlit run`, `pytest`,
# `scripts/build_index.py` -- reaches this module, and nothing may read `os.environ` before it.
# The alternative is a `load_env_file()` call at the top of four files, which works until
# somebody adds a fifth. Names only in the log: never the value.
_LOADED_FROM_ENV_FILE = load_env_file()
if _LOADED_FROM_ENV_FILE:
    log.debug("loaded %s from %s", ", ".join(_LOADED_FROM_ENV_FILE), ENV_FILE.name)
