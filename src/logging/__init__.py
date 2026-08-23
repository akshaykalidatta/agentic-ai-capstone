"""
Tracing and audit logging.

`trace_logger` answers "what ran and how long did it take"; `audit_logger` answers "can this
decision be defended in six months". Only the second is append-only.

NOTE: this package shadows the stdlib `logging`. Safe -- Python 3 uses absolute imports and it
is only reachable as `src.logging` -- unless `src/` itself lands on `sys.path`. First place to
look if an import ever behaves strangely.
"""
