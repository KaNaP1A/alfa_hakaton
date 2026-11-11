"""Serialized artifact writers on the supported macOS/Linux platforms."""

from contextlib import contextmanager
from pathlib import Path


@contextmanager
def output_lock(output):
    import fcntl

    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".write.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another build/embed is writing this output directory") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
