from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(tags=["identity"])


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata() -> JSONResponse:
    return JSONResponse(
        content={
            "resource": settings.OAUTH_EXPECTED_AUDIENCE,
            "authorization_servers": [settings.GATEWAY_BASE_URL],
            "scopes_supported": [
                "mcp:tools:read",
                "mcp:tools:write",
            ],
        }
    )
