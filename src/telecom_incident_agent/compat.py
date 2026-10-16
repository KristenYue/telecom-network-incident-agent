"""Narrow runner for deterministic offline coroutines.

The managed Windows sandbox used during development cannot close even a trivial
``asyncio.run`` loop.  Our Windows fixture adapter has no yielding operations,
so this helper can drive it to completion.  It deliberately rejects any real
awaitable yield; production API servers and Linux CI use normal asyncio.
"""

from __future__ import annotations

from collections.abc import Coroutine
import asyncio
import sys
from typing import Any


def run_non_yielding(coroutine: Coroutine[Any, Any, Any]) -> Any:
    if sys.platform != "win32":
        return asyncio.run(coroutine)
    try:
        yielded = coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise RuntimeError(
        "offline coroutine yielded control; run it with a functional asyncio event loop"
        f" (yielded={yielded!r})"
    )
