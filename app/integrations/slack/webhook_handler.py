import json

from app.config import settings
from app.integrations.slack.signature import is_timestamp_fresh, verify_slack_signature

_MAX_AGE_SECONDS = 300
_DEDUP_TTL_SECONDS = 3600
_EVENTS_STREAM = "events:slack"
_DEDUP_PREFIX = "webhook:slack:"


class SlackWebhookHandler:
    def __init__(self, redis):
        self._redis = redis

    def verify_signature(self, timestamp: str, signature: str, body: bytes) -> bool:
        if not timestamp or not signature:
            return False
        if not is_timestamp_fresh(timestamp, _MAX_AGE_SECONDS):
            return False
        return verify_slack_signature(settings.SLACK_SIGNING_SECRET, timestamp, body, signature)

    async def handle_url_verification(self, body: dict) -> dict:
        return {"challenge": body.get("challenge", "")}

    async def is_duplicate(self, event_id: str) -> bool:
        if not event_id:
            return False
        created = await self._redis.set(f"{_DEDUP_PREFIX}{event_id}", "1", nx=True, ex=_DEDUP_TTL_SECONDS)
        return not created

    async def publish_event(self, event_id: str, event_type: str, timestamp: str, payload: str) -> None:
        await self._redis.xadd(
            _EVENTS_STREAM,
            {
                "event_id": event_id,
                "type": event_type,
                "ts": timestamp,
                "payload": payload,
            },
        )

    async def process_webhook(self, raw_body: bytes, timestamp: str) -> dict:
        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            raise ValueError("invalid JSON")

        if not isinstance(body, dict):
            raise ValueError("invalid JSON")

        if body.get("type") == "url_verification":
            return await self.handle_url_verification(body)

        event_id = body.get("event_id", "")
        if await self.is_duplicate(event_id):
            return {"ok": True, "duplicate": True}

        await self.publish_event(
            event_id=event_id,
            event_type=body.get("type", ""),
            timestamp=timestamp,
            payload=raw_body.decode("utf-8", "replace"),
        )

        return {"ok": True}
