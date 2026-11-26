from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.memory.models import SessionContext

_sessions: dict[str, SessionContext] = {}
_lock = RLock()
_stripes = tuple(RLock() for _ in range(64))
MAX_SESSIONS = 1000


class SessionNotFoundError(ValueError):
    pass


class SessionTargetError(ValueError):
    pass


class SessionCapacityError(RuntimeError):
    pass


@contextmanager
def session_scope(usuario_id: str, session_id: str | None, colaborador_id: str | None):
    """Serialize an entire turn, including confirmation, without a growing lock map."""
    ident = session_id or str(uuid4())
    with _stripes[hash(ident) % len(_stripes)]:
        now = _now()
        with _lock:
            context = _sessions.get(ident)
            if session_id and (context is None or context.usuario_id != usuario_id):
                raise SessionNotFoundError("Sessao nao encontrada. Inicie sem session_id.")
            if context is not None and context.colaborador_id != colaborador_id:
                raise SessionTargetError("Nao altere o colaborador de uma sessao. Inicie outra.")
            expirou = context is not None and _is_expired(context, now)
            if context is None or expirou:
                if len(_sessions) >= MAX_SESSIONS and context is None:
                    # Do not evict turns that may be waiting on the database or provider.
                    for key, old in list(_sessions.items()):
                        if _is_expired(old, now):
                            stripe = _stripes[hash(key) % len(_stripes)]
                            if stripe.acquire(blocking=False):
                                try:
                                    _sessions.pop(key, None)
                                finally:
                                    stripe.release()
                    if len(_sessions) >= MAX_SESSIONS:
                        raise SessionCapacityError("Limite temporario de sessoes.")
                context = SessionContext(
                    session_id=ident, updated_at=now, usuario_id=usuario_id,
                    colaborador_id=colaborador_id,
                )
                _sessions[ident] = context
            context.updated_at = now
        try:
            yield context, expirou
        finally:
            save_session(context)


def save_session(context: SessionContext) -> None:
    with _lock:
        if _sessions.get(context.session_id) is not context:
            raise SessionNotFoundError("Sessao nao encontrada.")
        context.updated_at = _now()


def _is_expired(context: SessionContext, now: datetime) -> bool:
    return now - context.updated_at > timedelta(minutes=get_settings().session_ttl_minutes)


def _now() -> datetime:
    return datetime.now(timezone.utc)
