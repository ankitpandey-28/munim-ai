"""UUID version 7 (RFC 9562): 48-bit Unix-millisecond timestamp + random bits.

Generated in Python so ids are known before INSERT (needed for composite tenant keys and for
creating a shop and its first membership in one transaction under RLS). The database also has
``DEFAULT uuidv7()`` (PostgreSQL 18) as a fallback for rows inserted outside the ORM.
"""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7. Monotonic within a process (12-bit counter in rand_a)."""
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms <= _last_ms:
            _counter += 1
            if _counter > 0xFFF:  # counter exhausted within one millisecond: advance the clock
                _last_ms += 1
                _counter = 0
            now_ms = _last_ms
        else:
            _last_ms = now_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF  # random start, headroom
        rand_a = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 9562 variant
    value |= rand_b
    return uuid.UUID(int=value)
