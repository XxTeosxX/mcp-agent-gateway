from contextvars import ContextVar

current_user_id: ContextVar[str] = ContextVar("current_user_id")
current_user_scopes: ContextVar[frozenset[str]] = ContextVar("current_user_scopes", default=frozenset())
