"""Security primitives for BRRS; no external caches or secrets are written here."""
from collections import defaultdict, deque
from threading import Lock
import time

ATTEMPT_WINDOW_SECONDS = 15 * 60
ATTEMPT_LIMIT = 8
_lock = Lock()
_failed = defaultdict(deque)

def login_throttled(client_id: str, email: str) -> bool:
    key = (client_id, email)
    now = time.monotonic()
    with _lock:
        attempts = _failed[key]
        while attempts and now - attempts[0] >= ATTEMPT_WINDOW_SECONDS:
            attempts.popleft()
        return len(attempts) >= ATTEMPT_LIMIT

def note_failed_login(client_id: str, email: str) -> None:
    key = (client_id, email)
    now = time.monotonic()
    with _lock:
        attempts = _failed[key]
        while attempts and now - attempts[0] >= ATTEMPT_WINDOW_SECONDS:
            attempts.popleft()
        attempts.append(now)
        # Best effort local rate limiting. Production requires shared Redis or WAF.
        if len(_failed) > 10000:
            for k in list(_failed.keys())[:1000]:
                if not _failed[k] or now - _failed[k][-1] >= ATTEMPT_WINDOW_SECONDS:
                    del _failed[k]

def clear_failed_login(client_id: str, email: str) -> None:
    with _lock:
        _failed.pop((client_id, email), None)
