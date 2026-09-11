from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.memory.models import SessionContext


_sessions: dict[str, SessionContext] = {}
_lock = RLock()


def get_or_create_session(session_id: str | None = None) -> tuple[SessionContext, bool, bool]:
    now = _now()

    with _lock:
        if session_id is None:
            context = _new_session(now=now)
            _sessions[context.session_id] = context
            return context, True, False

        context = _sessions.get(session_id)
        if context is None:
            context = _new_session(session_id=session_id, now=now)
            _sessions[session_id] = context
            return context, True, False

        if _is_expired(context, now):
            context = _new_session(session_id=session_id, now=now)
            _sessions[session_id] = context
            return context, False, True

        context.updated_at = now
        return context, False, False


def save_session(context: SessionContext) -> None:
    context.updated_at = _now()

    with _lock:
        _sessions[context.session_id] = context


def _new_session(now: datetime, session_id: str | None = None) -> SessionContext:
    return SessionContext(session_id=session_id or str(uuid4()), updated_at=now)


def _is_expired(context: SessionContext, now: datetime) -> bool:
    ttl = timedelta(minutes=get_settings().session_ttl_minutes)
    return now - context.updated_at > ttl


def _now() -> datetime:
    return datetime.now(timezone.utc)
