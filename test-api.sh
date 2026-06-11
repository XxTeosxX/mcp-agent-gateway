#!/usr/bin/env bash
set -euo pipefail

# ── Smoke-test the gateway over MCP Streamable HTTP ────────────────────────────
#
# Designed for the local Docker stack in docker-compose.local.yml:
#   fastapi -> :8000   keycloak -> :8080 (realm mcp-gateway, admin/admin)
#   valkey  -> :6379   jaeger   -> :16686
#
#   docker compose -f docker-compose.local.yml up
#
# The /mcp/ endpoint is auth-guarded (AccessGuard): every call needs a Bearer JWT
# whose `iss` matches the gateway's OAUTH_ISSUER_URL and whose `aud` contains
# OAUTH_EXPECTED_AUDIENCE (http://localhost:8000/mcp/). The seeded realm
# (compose/local/keycloak/realm.json) hands both out via the `mcp-audience`
# mapper. The compose stack pins KC_HOSTNAME=http://localhost:8080, so on the
# HOST the issuer is `localhost:8080` (NOT `keycloak:8080`, which only resolves
# inside the compose network) — hence the localhost default below.
#
# Provide credentials one of three ways:
#   1. TOKEN=eyJ... ./test-api.sh                       # bring your own JWT
#   2. MCP_USER=rayray ./test-api.sh                    # resource-owner password grant
#      MCP_USER=june   ./test-api.sh                    # (MCP_PASSWORD defaults to <user>-pass)
#   3. CLIENT_ID=mcp-test CLIENT_SECRET=local-dev-only-not-secret ./test-api.sh
#                                                       # client_credentials grant
#
# Scopes drive what you can see/call (tools + prompts are scope-gated):
#   rayray  -> drive-user + slack-user  (full scope: drive + slack)
#   june    -> drive-user               (drive only)
#   jasmine -> slack-user               (slack only)
#   mcp-test-> service account, NO drive/slack roles -> empty tool/prompt lists
#            (still proves auth + routing work, but can't exercise upstreams)
#
# Upstream tools/prompts live under app/integrations/ after the DDD restructure:
#   Google Drive: app/integrations/google/tools.py  + prompts.py
#   Slack:        app/integrations/slack/tools.py
#   Async jobs:   app/integrations/google/job_tools.py
#
# Optional environment variables to exercise extra tools:
#   DRIVE_FILE_ID=<id>    -> calls drive-get-file-content and drive-export-large-file
#   SLACK_CHANNEL=<id>    -> calls slack-send-message
#
# Upstream tool calls (Drive, Slack) hit real APIs and require the corresponding
# shared tokens (GOOGLE_SHARED_REFRESH_TOKEN, SLACK_SHARED_BOT_TOKEN,
# SLACK_SHARED_USER_TOKEN). Without them they return an upstream auth error,
# which still proves request routing works.
#
# Run with bash (uses arrays/herestrings + `set -euo pipefail`): `bash test-api.sh`.
# ──────────────────────────────────────────────────────────────────────────────

BASE_URL="${BASE_URL:-http://localhost:8000}"
MCP_URL="$BASE_URL/mcp/"
MCP_ACCEPT="application/json, text/event-stream"

# Issuer must match the gateway's OAUTH_ISSUER_URL so the token `iss` validates.
OAUTH_ISSUER_URL="${OAUTH_ISSUER_URL:-http://localhost:8080/realms/mcp-gateway}"
KEYCLOAK_TOKEN_URL="${KEYCLOAK_TOKEN_URL:-$OAUTH_ISSUER_URL/protocol/openid-connect/token}"

# Confidential client used for resource-owner password grants (MCP_USER path).
# mcp-gateway carries the mcp-audience mapper + fullScopeAllowed, so user tokens
# get the right `aud` and the user's mcp-gateway client roles.
USER_CLIENT_ID="${USER_CLIENT_ID:-mcp-gateway}"
USER_CLIENT_SECRET="${USER_CLIENT_SECRET:-mcp-gateway-secret}"

# ── Resolve a Bearer token ────────────────────────────────────────────────────
# NB: read MCP_USER, NOT USERNAME — the OS already exports USERNAME (your login),
# so `USERNAME=rayray ...` would be silently shadowed by the ambient value.
if [ -z "${TOKEN:-}" ] && [ -n "${MCP_USER:-}" ]; then
  # Seeded users follow the `<username>-pass` convention (rayray-pass, june-pass).
  MCP_PASSWORD="${MCP_PASSWORD:-${MCP_USER}-pass}"
  echo "Fetching token for user '$MCP_USER' from Keycloak ($KEYCLOAK_TOKEN_URL)..."
  TOKEN=$(curl -s -X POST "$KEYCLOAK_TOKEN_URL" \
    -d "grant_type=password" \
    -d "client_id=${USER_CLIENT_ID}" \
    -d "client_secret=${USER_CLIENT_SECRET}" \
    -d "username=${MCP_USER}" \
    -d "password=${MCP_PASSWORD}" \
    -d "scope=openid" \
    | jq -r '.access_token // empty')
fi

if [ -z "${TOKEN:-}" ] && [ -n "${CLIENT_ID:-}" ]; then
  echo "Fetching token from Keycloak ($KEYCLOAK_TOKEN_URL)..."
  TOKEN=$(curl -s -X POST "$KEYCLOAK_TOKEN_URL" \
    -d "grant_type=client_credentials" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_secret=${CLIENT_SECRET:?CLIENT_SECRET required when CLIENT_ID is set}" \
    | jq -r '.access_token // empty')
fi

if [ -z "${TOKEN:-}" ]; then
  echo "ERROR: no Bearer token. Set TOKEN=..., MCP_USER=rayray, or CLIENT_ID + CLIENT_SECRET." >&2
  echo "       (/mcp/ is auth-guarded; only /health is public.)" >&2
  echo "       Token issuer must match OAUTH_ISSUER_URL ($OAUTH_ISSUER_URL)." >&2
  exit 1
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

# Simple section counter printed as "N. Title".
NUM=0
section() {
  NUM=$((NUM + 1))
  echo "================================================"
  echo "  $NUM. $1"
  echo "================================================"
}

# Extract the JSON payload from an MCP response body (handles both raw JSON and
# SSE-framed `data:` lines that Streamable HTTP returns).
sse_json() {
  if grep -q '^data:' <<<"$1"; then
    sed -n 's/^data: //p' <<<"$1"
  else
    printf '%s' "$1"
  fi
}

# Helper: POST to MCP with the active session.
post_mcp() {
  local body="$1"
  curl -s -X POST "$MCP_URL" \
    -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -H "Accept: $MCP_ACCEPT" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "$body"
}

# Helper: pretty-print an MCP response through sse_json + jq.
show_mcp() {
  sse_json "$1" | jq . || echo "$1"
}

# Helper: check whether a tool name appears in the tools/list response.
tool_exists() {
  local name="$1"
  sse_json "$TOOLS_BODY" | jq -e --arg n "$name" '.result.tools[]? | select(.name == $n)' >/dev/null 2>&1
}

section "Health Check"
curl -s "$BASE_URL/health" | jq .
echo

section "OAuth Protected Resource (RFC 9728)"
curl -s "$BASE_URL/.well-known/oauth-protected-resource" | jq .
echo

section "MCP — Initialize"
INIT_DUMP=$(curl -s -D - -X POST "$MCP_URL" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -H "Accept: $MCP_ACCEPT" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {"name": "curl-client", "version": "1.0"}
    }
  }')

# Split headers (before first blank line) from body.
INIT_HEADERS=$(awk 'BEGIN{h=1} /^\r?$/{h=0;next} h{print}' <<<"$INIT_DUMP")
INIT_BODY=$(awk 'BEGIN{h=1} /^\r?$/{if(h){h=0;next}} !h{print}' <<<"$INIT_DUMP")

SESSION_ID=$(grep -i "^mcp-session-id:" <<<"$INIT_HEADERS" | awk '{print $2}' | tr -d '\r')
sse_json "$INIT_BODY" | jq . || echo "$INIT_BODY"
echo
echo "Session ID: $SESSION_ID"
echo

if [ -z "$SESSION_ID" ]; then
  echo "ERROR: No session ID received (check token/auth). Cannot proceed." >&2
  exit 1
fi

section "MCP — Notifications Initialized"
curl -s -o /dev/null -w "HTTP %{http_code} (empty body expected for notifications)\n" \
  -X POST "$MCP_URL" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -H "Accept: $MCP_ACCEPT" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
  }'
echo

section "MCP — List Tools"
TOOLS_BODY=$(post_mcp '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/list"
}')
show_mcp "$TOOLS_BODY"
echo

section "MCP — Call Tool (drive-list-recent)"
echo "(requires GOOGLE_SHARED_REFRESH_TOKEN provisioned; otherwise returns an upstream auth error)"
CALL_BODY=$(post_mcp '{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "drive-list-recent",
    "arguments": {"days": 7, "max_results": 5}
  }
}')
show_mcp "$CALL_BODY"
echo

section "MCP — Call Tool (drive-search-files)"
echo "(structured filters — gateway builds the Drive query safely)"
SEARCH_BODY=$(post_mcp '{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "drive-search-files",
    "arguments": {
      "full_text": "proposal",
      "max_results": 5
    }
  }
}')
show_mcp "$SEARCH_BODY"
echo

if [ -n "${DRIVE_FILE_ID:-}" ]; then
  section "MCP — Call Tool (drive-get-file-content)"
  echo "(DRIVE_FILE_ID=$DRIVE_FILE_ID)"
  GET_FILE_BODY=$(post_mcp "$(printf '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"drive-get-file-content","arguments":{"file_id":"%s"}}}' "$DRIVE_FILE_ID")")
  show_mcp "$GET_FILE_BODY"
  echo

  section "MCP — Call Tool (drive-export-large-file)"
  echo "(starts async export; polls with wait-for-job. DRIVE_FILE_ID=$DRIVE_FILE_ID)"
  EXPORT_BODY=$(post_mcp "$(printf '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"drive-export-large-file","arguments":{"file_id":"%s","format":"pdf"}}}' "$DRIVE_FILE_ID")")
  show_mcp "$EXPORT_BODY"
  echo

  JOB_ID=$(sse_json "$EXPORT_BODY" | jq -r '.result.content[0].text | fromjson? | .job_id // empty')
  if [ -n "$JOB_ID" ]; then
    echo "Job ID: $JOB_ID"
    section "MCP — Call Tool (wait-for-job)"
    WAIT_BODY=$(post_mcp "$(printf '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"wait-for-job","arguments":{"job_id":"%s","timeout_seconds":10}}}' "$JOB_ID")")
    show_mcp "$WAIT_BODY"
    echo
  fi
else
  echo "Skipping drive-get-file-content / drive-export-large-file (set DRIVE_FILE_ID to exercise)."
  echo
fi

if tool_exists "slack-search-messages"; then
  section "MCP — Call Tool (slack-search-messages)"
  echo "(requires SLACK_SHARED_USER_TOKEN provisioned; otherwise returns an upstream auth error)"
  SLACK_SEARCH_BODY=$(post_mcp '{
    "jsonrpc": "2.0",
    "id": 9,
    "method": "tools/call",
    "params": {
      "name": "slack-search-messages",
      "arguments": {
        "query": "deploy",
        "count": 5
      }
    }
  }')
  show_mcp "$SLACK_SEARCH_BODY"
  echo

  if [ -n "${SLACK_CHANNEL:-}" ]; then
    section "MCP — Call Tool (slack-send-message)"
    echo "(requires SLACK_SHARED_BOT_TOKEN provisioned; posts to SLACK_CHANNEL=$SLACK_CHANNEL)"
    SLACK_SEND_BODY=$(post_mcp "$(printf '{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"slack-send-message","arguments":{"channel":"%s","text":"Smoke test from test-api.sh"}}}' "$SLACK_CHANNEL")")
    show_mcp "$SLACK_SEND_BODY"
    echo
  else
    echo "Skipping slack-send-message (set SLACK_CHANNEL to exercise)."
    echo
  fi
else
  echo "Skipping Slack tools (token lacks slack-user role)."
  echo
fi

section "MCP — List Prompts"
PROMPTS_BODY=$(post_mcp '{
  "jsonrpc": "2.0",
  "id": 11,
  "method": "prompts/list"
}')
show_mcp "$PROMPTS_BODY"
echo

section "MCP — Get Prompt (drive-find-document)"
echo "(scope-gated: requires mcp:google:read — returns prompt messages for the MCP client)"
GET_PROMPT_BODY=$(post_mcp '{
  "jsonrpc": "2.0",
  "id": 12,
  "method": "prompts/get",
  "params": {
    "name": "drive-find-document",
    "arguments": {
      "description": "Q3 proposal for Acme",
      "client_name": "Acme"
    }
  }
}')
show_mcp "$GET_PROMPT_BODY"
echo

section "Done!"
