"""Idempotently add the mcp-gateway client, client roles, and 3 test users to realm.json.

Run once: `python app/compose/local/keycloak/seed_rbac.py`
Safe to re-run — existing entries are replaced, not duplicated.
"""

import json
import pathlib
import uuid

HERE = pathlib.Path(__file__).parent
REALM = HERE / "realm.json"
CLIENT_ID = "mcp-gateway"
CLIENT_UUID = "11111111-1111-1111-1111-111111111111"
AUDIENCE = "http://localhost:8000/mcp/"
SECRET = "mcp-gateway-secret"  # dev only

CLIENT = {
    "id": CLIENT_UUID,
    "clientId": CLIENT_ID,
    "enabled": True,
    "protocol": "openid-connect",
    "publicClient": False,
    "clientAuthenticatorType": "client-secret",
    "secret": SECRET,
    "standardFlowEnabled": False,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": True,
    "serviceAccountsEnabled": False,
    "fullScopeAllowed": True,
    "redirectUris": [],
    "webOrigins": [],
    "defaultClientScopes": ["web-origins", "acr", "roles", "profile", "basic", "email"],
    "optionalClientScopes": ["address", "phone", "offline_access", "microprofile-jwt"],
    "protocolMappers": [
        {
            "name": "mcp-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.custom.audience": AUDIENCE,
                "id.token.claim": "false",
                "access.token.claim": "true",
            },
        }
    ],
}

CLIENT_ROLES = [
    {"name": "drive-user", "description": "May use Google Drive tools"},
    {"name": "slack-user", "description": "May use Slack tools"},
    {"name": "admin-user", "description": "May read the admin usage API (mcp:admin:read)"},
]

USERS = [
    ("june", "june-pass", ["drive-user"]),
    ("rayray", "rayray-pass", ["drive-user", "slack-user"]),
    ("jasmine", "jasmine-pass", ["slack-user"]),
    ("admin", "admin-pass", ["admin-user"]),
]


def _user(username: str, password: str, roles: list[str]) -> dict:
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"mcp-{username}")),
        "username": username,
        "enabled": True,
        "emailVerified": True,
        "email": f"{username}@example.com",
        "firstName": username.title(),
        "lastName": "Test",
        "requiredActions": [],
        "credentials": [{"type": "password", "value": password, "temporary": False}],
        "realmRoles": ["default-roles-mcp-gateway"],
        "clientRoles": {CLIENT_ID: roles},
    }


def main() -> None:
    realm = json.loads(REALM.read_text())

    realm["clients"] = [c for c in realm.get("clients", []) if c.get("clientId") != CLIENT_ID]
    realm["clients"].append(CLIENT)

    realm.setdefault("roles", {}).setdefault("client", {})[CLIENT_ID] = CLIENT_ROLES

    seeded = {u for u, _p, _r in USERS}
    realm["users"] = [u for u in realm.get("users", []) if u.get("username") not in seeded]
    realm["users"].extend(_user(u, p, r) for u, p, r in USERS)

    REALM.write_text(json.dumps(realm, indent=2) + "\n")
    print(f"seeded client '{CLIENT_ID}', {len(CLIENT_ROLES)} roles, {len(USERS)} users")


if __name__ == "__main__":
    main()
