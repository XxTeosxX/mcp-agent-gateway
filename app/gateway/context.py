from contextvars import ContextVar

current_user_id: ContextVar[str] = ContextVar("current_user_id")
