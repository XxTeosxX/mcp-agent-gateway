import functools
import json
import logging
import time

import tiktoken

from app.shared.context import current_user_id

logger = logging.getLogger("app.usage")


@functools.cache
def _get_encoding() -> "tiktoken.Encoding":
    # Loaded lazily on first token count, not at import. tiktoken fetches the
    # BPE encoding (cached after first load), so deferring keeps startup working
    # offline and only pays the cost if usage tracking actually runs.
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


async def record_usage(redis, user_id: str, tool: str, in_tokens: int, out_tokens: int) -> None:
    await redis.xadd(
        f"usage:{user_id}",
        {
            "ts": str(time.time()),
            "tool": tool,
            "in_tokens": str(in_tokens),
            "out_tokens": str(out_tokens),
        },
    )


class UsageRecorderHolder:
    def __init__(self) -> None:
        self._redis = None

    def init(self, redis) -> None:
        self._redis = redis

    def get(self):
        return self._redis


usage_recorder = UsageRecorderHolder()


def _result_text(result) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def track_usage(tool_name: str):

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(arguments: dict):
            result = await handler(arguments)
            try:
                redis = usage_recorder.get()
                user_id = current_user_id.get("")
                if redis is not None and user_id:
                    in_tokens = count_tokens(json.dumps(arguments, default=str))
                    out_tokens = count_tokens(_result_text(result))
                    await record_usage(redis, user_id, tool_name, in_tokens, out_tokens)
            except Exception:
                logger.warning("usage recording failed for %s", tool_name, exc_info=True)
            return result

        return wrapper

    return decorator
