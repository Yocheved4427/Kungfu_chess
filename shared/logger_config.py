import logging
import sys

# ---------------------------------------------------------------------------
# Kung Fu Chess – Logging configuration
# ---------------------------------------------------------------------------
# Single place that configures Python's logging module for every real
# entry point (main.py's CLI/text pipeline, main_gui.py's OpenCV GUI).
# Not core/config.py: core.models' own docstring states core/ is pure
# value objects — "no business logic, no I/O, no side-effects" — and
# registering a handler is a side effect, so this lives at the repo root
# next to the entry points that call it instead.
#
# Every other module logs via its own ``logging.getLogger(__name__)``
# (stdlib convention: hierarchical logger names, no per-module setup) —
# only the entry point calls setup_logging(), once, before anything else
# runs.
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure the root logger: *default_level*, timestamped format, stderr.

    Safe to call more than once — a second call is a no-op if the root
    logger already has a handler, so log lines are never duplicated.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(default_level)
