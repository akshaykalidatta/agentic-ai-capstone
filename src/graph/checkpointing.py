"""
Checkpointer construction. One function, because building a working `SqliteSaver` takes three
non-obvious decisions and two of them are invisible until a review is already suspended.

`memory` and `none` stay in `support_graph._default_checkpointer` -- they need no help.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class JsonMetadataSerializer:
    """
    The untyped `dumps`/`loads` pair that `langgraph-checkpoint-sqlite` calls on the metadata
    column, reimplemented because the installed `langgraph-checkpoint` no longer provides it.

    `JsonPlusSerializer` used to expose four methods. Core 4.x keeps only the typed pair
    (`dumps_typed`/`loads_typed`, which the checkpoint blob still uses) and drops the untyped
    one; the sqlite saver was written against the older core and still calls
    `self.jsonplus_serde.dumps(...)`, so every `put()` raised
    `AttributeError: 'JsonPlusSerializer' object has no attribute 'dumps'` -- i.e. no review
    could ever be written to disk.

    JSON specifically, and not msgpack: the saver's own filter compiles to
    `json_extract(CAST(metadata AS TEXT), '$.key')` (see its `utils.py`), so that column has to
    be UTF-8 JSON text or `list(filter=...)` matches nothing and reports it as "no results"
    rather than as an error.

    `default=str` on the way out because metadata must never be the reason a suspended review
    cannot be saved. It is the filter index -- source, step, parents, plus whatever the config
    carried -- not the state. State restore reads the checkpoint blob, which is untouched, so a
    value that degrades to its repr here costs a filter, not a resume.
    """

    def dumps(self, obj: Any) -> bytes:
        # Compact separators: the saver's dict/list filters compare against
        # `json.dumps(value, separators=(",", ":"))`, and SQLite's json_extract minifies what it
        # returns, so writing minified keeps the stored bytes and the compared bytes identical.
        return json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def loads(self, data: bytes | str) -> Any:
        return json.loads(data)


def repair_metadata_serializer(saver: Any) -> Any:
    """
    Install `JsonMetadataSerializer` on a saver whose own one is missing `dumps`.

    Conditional on purpose. On a matched pair of packages the library's serializer handles more
    types than `default=str` does, and it should stay in charge; this only fills a hole. Which
    means the day the sqlite saver catches up with core, this becomes a no-op and nobody has to
    remember to remove it.
    """
    serde = getattr(saver, "jsonplus_serde", None)
    if serde is not None and not hasattr(serde, "dumps"):
        saver.jsonplus_serde = JsonMetadataSerializer()
        log.debug(
            "%s lacks an untyped dumps/loads; using JsonMetadataSerializer for the metadata "
            "column", type(serde).__name__,
        )
    return saver


def sqlite_saver(path: str | Path, *, check_same_thread: bool = False) -> Any:
    """
    A `SqliteSaver` on `path`, ready to survive a process restart.

    Three decisions live here so that the app and `tests/test_hitl.py` cannot drift apart on
    any of them:

    1. **We own the connection.** `SqliteSaver.from_conn_string` is a `@contextmanager` in
       recent versions -- it *yields* a saver, so returning it hands back a context-manager
       object and the graph fails on its first write.
    2. **`check_same_thread=False`.** Streamlit resumes from a worker thread that is not the
       one that opened the connection.
    3. **The metadata serializer is repaired if it needs it** (see above).

    The import is local: `src/graph/` must stay importable with no langgraph installed, which
    is what lets the 109 offline tests and every `--walk` run work on a bare checkout.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database), check_same_thread=check_same_thread)
    return repair_metadata_serializer(SqliteSaver(connection))
