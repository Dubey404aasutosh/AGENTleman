import threading
import time
from models import SessionState

_DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes — lazy eviction, no persistence (per PRD non-goals)


class SessionStore:
    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS):
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._data: dict[str, tuple[SessionState, float]] = {}

    def get(self, session_id: str, current_time: float | None = None) -> SessionState | None:
        now = current_time if current_time is not None else time.time()
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            state, ts = entry
            if now - ts > self._ttl_seconds:
                del self._data[session_id]
                return None
            return state

    def set(self, session_id: str, state: SessionState, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            self._data[session_id] = (state, ts)   # overwrite = idempotent reset

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def count(self) -> int:
        with self._lock:
            return len(self._data)


_store = SessionStore()

def get(session_id: str, current_time: float | None = None) -> SessionState | None:
    return _store.get(session_id, current_time=current_time)

def set(session_id: str, state: SessionState, timestamp: float | None = None) -> None:
    _store.set(session_id, state, timestamp=timestamp)

def delete(session_id: str) -> None:
    _store.delete(session_id)

def count() -> int:
    return _store.count()

