import time

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN_SCOPE = "mcp:admin:read"


def require_admin_scope(request: Request) -> None:
    user = getattr(request.state, "user", None)
    scopes = (user or {}).get("scopes", [])
    if _ADMIN_SCOPE not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: mcp:admin:read")


@router.get("/usage/{user_id}")
async def get_usage(
    user_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
) -> dict:
    require_admin_scope(request)
    redis = request.app.state.redis
    cutoff = time.time() - hours * 3600

    entries = await redis.xrange(f"usage:{user_id}")
    events = []
    total_in = 0
    total_out = 0
    for _entry_id, fields in entries:
        ts = float(fields["ts"])
        if ts < cutoff:
            continue
        in_tokens = int(fields["in_tokens"])
        out_tokens = int(fields["out_tokens"])
        total_in += in_tokens
        total_out += out_tokens
        events.append({"ts": ts, "tool": fields["tool"], "in_tokens": in_tokens, "out_tokens": out_tokens})

    return {
        "user_id": user_id,
        "hours": hours,
        "count": len(events),
        "total_in_tokens": total_in,
        "total_out_tokens": total_out,
        "events": events,
    }
