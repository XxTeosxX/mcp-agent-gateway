import json
import logging

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.integrations.slack.signature import is_timestamp_fresh, verify_slack_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_MAX_AGE_SECONDS = 300
_DEDUP_TTL_SECONDS = 3600
_EVENTS_STREAM = "events:slack"
_DEDUP_PREFIX = "webhook:slack:"


@router.post("/slack")
async def slack_webhook(request: Request) -> dict:
    if not settings.SLACK_SIGNING_SECRET:
        raise HTTPException(status_code=503, detail="webhook not configured")

    raw = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="missing signature headers")
    if not is_timestamp_fresh(timestamp, _MAX_AGE_SECONDS):
        raise HTTPException(status_code=401, detail="stale timestamp")
    if not verify_slack_signature(settings.SLACK_SIGNING_SECRET, timestamp, raw, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid JSON")

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    redis = request.app.state.redis
    event_id = body.get("event_id", "")
    if event_id:
        created = await redis.set(f"{_DEDUP_PREFIX}{event_id}", "1", nx=True, ex=_DEDUP_TTL_SECONDS)
        if not created:
            return {"ok": True, "duplicate": True}

    await redis.xadd(
        _EVENTS_STREAM,
        {
            "event_id": event_id,
            "type": body.get("type", ""),
            "ts": timestamp,
            "payload": raw.decode("utf-8", "replace"),
        },
    )
    return {"ok": True}
