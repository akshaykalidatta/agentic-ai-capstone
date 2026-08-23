"""
The `.env` loader, and the two guards that keep a key out of git.

    python -m pytest tests/test_config.py -v

No key, no network, no langgraph: this is stdlib parsing plus two assertions about files that
are in the repo.
"""

from __future__ import annotations

import os

from src.utils.config import ENV_FILE, REPO_ROOT, load_env_file, parse_env_file

# ------------------------------------------------------------------------------- the parser


def test_parse_handles_the_shapes_a_hand_edited_file_actually_has():
    parsed = parse_env_file(
        "\n".join(
            [
                "# a comment",
                "",
                "GROQ_API_KEY=gsk_plain",
                'QUOTED="double"',
                "SINGLE='single'",
                "export EXPORTED=prefixed",
                "  SPACED  =  padded  ",
                "JUNK_WITHOUT_EQUALS",
            ]
        )
    )
    assert parsed == {
        "GROQ_API_KEY": "gsk_plain",
        "QUOTED": "double",
        "SINGLE": "single",
        "EXPORTED": "prefixed",
        "SPACED": "padded",
    }


def test_a_hash_inside_an_unquoted_value_is_part_of_the_value():
    """
    An API key is opaque. Stripping everything after a `#` is the usual dotenv convenience and
    it would silently truncate a key that contains one -- a failure that reads as "invalid API
    key" from the provider, hours away from the file that caused it.
    """
    assert parse_env_file("KEY=abc#def")["KEY"] == "abc#def"


# -------------------------------------------------------------------------------- the loader


def test_the_file_fills_in_a_missing_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("EXAMPLE_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_TOKEN=from-the-file\n", encoding="utf-8")

    assert load_env_file(env_file) == ["EXAMPLE_TOKEN"]
    assert os.environ["EXAMPLE_TOKEN"] == "from-the-file"


def test_a_real_environment_variable_wins(tmp_path, monkeypatch):
    """
    The precedence that makes the file safe to leave lying around: a shell variable overrides
    it, so a stale `.env` can never shadow what CI or a scheduled run injected, and a second
    key can be tried for one run without editing anything.
    """
    monkeypatch.setenv("EXAMPLE_TOKEN", "from-the-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_TOKEN=from-the-file\n", encoding="utf-8")

    assert load_env_file(env_file) == [], "the file overrode a variable already in the shell"
    assert os.environ["EXAMPLE_TOKEN"] == "from-the-shell"
    assert load_env_file(env_file, override=True) == ["EXAMPLE_TOKEN"]
    assert os.environ["EXAMPLE_TOKEN"] == "from-the-file"


def test_no_env_file_is_not_an_error(tmp_path):
    """
    `--gate`, `--no-model` and this suite need no key. Requiring a secrets file to run them
    would hand a bare checkout a new way to fail.
    """
    assert load_env_file(tmp_path / "absent") == []


# ------------------------------------------------------------- the key cannot reach the repo


def test_the_env_file_is_gitignored():
    """Executable version of the rule, so rewriting .gitignore cannot quietly repeal it."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ENV_FILE.name in [line.strip() for line in ignored]


def test_the_committed_template_carries_no_value():
    """
    `.env.example` is tracked. If someone fills it in instead of copying it, the key ships in
    the next commit -- so assert the template is empty rather than trusting the instruction at
    the top of it.
    """
    template = REPO_ROOT / ".env.example"
    assert template.is_file(), "the template the setup docs tell you to copy is missing"
    assert parse_env_file(template.read_text(encoding="utf-8")) == {"GROQ_API_KEY": ""}
