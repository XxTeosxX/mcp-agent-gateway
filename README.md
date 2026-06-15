# MCP Agent Gateway

> A secure, production-minded gateway that gives AI agents **audited, least-privilege access** to Google Drive and Slack over the Model Context Protocol — without ever leaking the user's identity token to a third party.

<p align="center">
  <a href="https://github.com/xxteosxx/mcp-agent-gateway/actions/workflows/ci.yml">
    <img alt="CI" src="https://github.com/xxteosxx/mcp-agent-gateway/actions/workflows/ci.yml/badge.svg">
  </a>
  <img alt="coverage" src="https://img.shields.io/badge/coverage-93%25-2ea44f">
  <img alt="bandit" src="https://img.shields.io/badge/bandit-0_high-2ea44f">
  <img alt="confused deputy" src="https://img.shields.io/badge/Confused_Deputy-proven-2ea44f">
</p>

<p align="center">
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white">
  <img alt="OAuth 2.1" src="https://img.shields.io/badge/OAuth-2.1-EB5424?logo=auth0&logoColor=white">
  <img alt="RFC 9728" src="https://img.shields.io/badge/RFC-9728-555">
  <img alt="RFC 7591" src="https://img.shields.io/badge/RFC-7591-555">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-Streamable_HTTP-6E56CF">
  <img alt="license MIT" src="https://img.shields.io/badge/license-MIT-blue">
</p>

---

## The problem this solves

AI agents want to read your Drive and post to your Slack. The naïve way — forward the
user's bearer token straight to the upstream API — is a textbook **Confused Deputy
vulnerability**: the upstream can't tell whether the agent was actually authorized to act,
and a single stolen token unlocks everything.

This gateway refuses to do that. It runs **two independent OAuth trust boundaries**:

```
 Agent ──Bearer JWT──▶  GATEWAY  ──per-service OAuth token──▶  Google / Slack
        (downstream)      │                  (upstream)
                          └── the downstream JWT is NEVER forwarded upstream
```

The downstream client-to-gateway flow is OAuth 2.1: authorization code with PKCE for users, or client credentials for service accounts; upstream tokens are isolated per-provider OAuth 2.0 tokens.

The separation is **proven by a regression test** (`test_confused_deputy`) that asserts the
downstream JWT never appears in any upstream request — so the guarantee can't silently rot.

---

## Highlight reel

| What | How it's done | Why it's hard |
|---|---|---|
| 🛡️ **Confused Deputy prevention** | Dual OAuth flows, per-integration token mint | Most gateways forward the caller's token by default |
| 🔑 **Standards-based auth** | OAuth 2.1 + RFC 9728 PRM + RFC 7591 Dynamic Client Registration | Any compliant MCP client connects with zero custom glue |
| 🔒 **Tokens encrypted at rest** | Fernet (authenticated encryption), one key per provider | Redis compromise ≠ credential compromise |
| ⏱️ **Atomic rate limiting** | Fixed-window counter in a single Redis **Lua** script (`INCR` + `PEXPIRE`) | Naïve counters race under concurrency |
| 📈 **Usage metering** | `tiktoken` token counting → Redis Streams + admin API | Per-user cost/visibility without log scraping |
| ⚙️ **Async job queue** | Redis Streams consumer groups + ownership guard | Large Drive exports outlive a single request |
| 📨 **Signed webhooks** | Slack HMAC v0 + timestamp freshness + replay guard + idempotency | Webhooks are a classic spoofing/replay vector |
| 🔭 **Distributed tracing** | OpenTelemetry zero-code auto-instrumentation (FastAPI + httpx), OTLP export, trace-id stamped on the request log event | Correlating a request across middleware, MCP, and upstream calls is otherwise guesswork |
| 🧱 **Clean DDD architecture** | Bounded contexts: `identity` · `integrations` · `mcp` · `middleware` · `shared` | New integration = one folder, one contract |

---

## Architecture

```mermaid
graph TB
    subgraph Agent["AI Agent"]
        A[MCP Client]
    end
    subgraph GW["MCP Gateway · FastAPI"]
        B[AccessGuard<br/>JWT validation]
        C[RateLimiter<br/>atomic Lua]
        D[UsageMeter<br/>Redis Streams]
        E[Tool Registry<br/>Drive · Slack · Jobs]
    end
    subgraph IdP["Identity Provider"]
        F[Keycloak<br/>OAuth 2.1]
    end
    subgraph Up["Upstream APIs"]
        G[Google Drive]
        H[Slack]
    end

    A -->|Bearer JWT · downstream| B
    B -->|validate RS256| F
    F -->|claims| B
    B --> C --> D --> E
    E -->|per-service OAuth token · upstream| G
    E -->|per-service OAuth token · upstream| H

    classDef agent fill:#1565c0,stroke:#0d3c75,stroke-width:2px,color:#fff;
    classDef gw fill:#ef6c00,stroke:#9c4500,stroke-width:2px,color:#fff;
    classDef idp fill:#c62828,stroke:#7f1717,stroke-width:2px,color:#fff;
    classDef up fill:#2e7d32,stroke:#1b4d1f,stroke-width:2px,color:#fff;

    class A agent;
    class B,C,D,E gw;
    class F idp;
    class G,H up;
```

**Request path:** `AccessGuard` (Bearer → validate → `request.state.user`; bypasses public/meta
paths such as `/health`, `/.well-known/*`, `/docs`, `/openapi.json`, `/oauth/authorize`, and
`/webhooks/*`) → `request_logger` → MCP app at `/mcp/`. Middleware wraps the MCP route itself,
so the protocol traffic is authenticated like everything else.

**Project layout** (source under `app/`):

```
app/
  main.py            # lifespan: DI wiring, token seeding, jobs worker
  config.py          # pydantic-settings
  api/               # admin/usage + Slack webhook routers
  authorization/     # OAuth authorize + AS metadata
  identity/          # JWT validation, JWKS, RFC 7591 client registration
  mcp/               # MCP server, ASGI app, event store, health
  middleware/        # AccessGuard, OriginGuard, rate limiter, security headers, request logger
  integrations/      # base.py contract + google/, slack/ (client, token_store, tools)
  shared/            # Redis, Store, HTTP client, usage, dependencies, exceptions
```

---

## Capabilities

### Google Drive
| Tool | Does |
|---|---|
| `drive-search-files` | Search files by query / MIME type |
| `drive-get-file-content` | Fetch a file's content |
| `drive-list-recent` | List recently modified files |
| `drive-export-large-file` | Enqueue a large export as an async job |

> [!NOTE]
> **One-time human consent is required — by design, because this runs against a
> free @gmail.com account.** Google only lets apps skip per-user consent through
> domain-wide delegation (Workspace-only), and a service account on a consumer
> account can't see the owner's Drive root. So a one-time OAuth consent from the
> owner is unavoidable — but it happens out-of-band in `gcloud`, not in the gateway.
>
> Consent is not the same as sharing the password: the owner grants scoped,
> read-only (`drive.readonly`), revocable access once, and the gateway only ever
> stores an encrypted refresh token in Redis.
>
> **Provisioning (once):**
>
> ```bash
> # Build the client-id-file from the env vars already in your .env — no download needed.
> echo "{\"installed\":{\"client_id\":\"$GOOGLE_CLIENT_ID\",\"client_secret\":\"$GOOGLE_CLIENT_SECRET\",\"redirect_uris\":[\"http://localhost\"],\"auth_uri\":\"https://accounts.google.com/o/oauth2/auth\",\"token_uri\":\"https://oauth2.googleapis.com/token\"}}" \
>   > google_oauth_client.json
>
> # The refresh token MUST be issued to the SAME OAuth client the gateway refreshes
> # with (GOOGLE_CLIENT_ID/SECRET) — Desktop-type client supports the loopback flow gcloud uses.
> gcloud auth application-default login \
>   --client-id-file=google_oauth_client.json \
>   --scopes=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
>
> rm google_oauth_client.json
>
> # Copy the refresh_token from the saved ADC file into .env:
> python3 -c "import json,pathlib; d=json.loads(pathlib.Path('~/.config/gcloud/application_default_credentials.json').expanduser().read_text()); print('GOOGLE_SHARED_REFRESH_TOKEN=' + d['refresh_token'])"
> ```
>
> On boot the gateway seeds `token:google:shared` from `GOOGLE_SHARED_REFRESH_TOKEN`
> (only if absent), and `get_valid_google_token` refreshes it on the first Drive
> call. After that, any gateway-authenticated user can use the Drive tools.

### Slack
| Tool | Does |
|---|---|
| `slack-send-message` | Post a message to a channel |
| `slack-search-messages` | Search message history |

> [!NOTE]
> **Planned improvement — structured Slack search (parity with Drive).** Today
> `slack-search-messages` takes a single `query` string in **Slack's own search syntax**
> (`deploy in:#ops`, `from:@user`), so the agent has to know the upstream DSL. `drive-search-files`
> already solves this the right way: the caller passes **structured, validated filters**
> (`name_contains`, `full_text`, `mime_type`, `in_folder`, `modified_after`) and the gateway
> builds the escaped Drive `q` **server-side** — no API query language leaks to the agent, and
> injection is impossible by construction. The next step is to give Slack search the same
> structured input (`from`, `in_channel`, `before`/`after`) and compose the Slack query
> internally, so every search tool speaks structured input, not a vendor DSL.

### Jobs
| Tool | Does |
|---|---|
| `wait-for-job` | Block on an async job until it completes (ownership-checked) |

Inbound: `POST /webhooks/slack` — HMAC-verified, replay-guarded, idempotent fan-out to a
`events:slack` stream.

> [!NOTE]
> **Bot token via env var — no per-user consent needed (unlike Drive).** A Slack
> bot token (`xoxb-`) is workspace-level: it represents the app, not a person, so
> a single shared token is the natural model — and Slack imposes **no app-review
> or verification gate** for a single-workspace install, so this works on the
> **free Slack plan**.
>
> **Provisioning (once):**
> 1. Create an app at [api.slack.com/apps](https://api.slack.com/apps).
> 2. Add a **Bot User** and the bot scopes the tools need (e.g. `chat:write`,
>    `channels:read`, `search:read`).
> 3. **Install to Workspace** — you approve it yourself as workspace admin; no
>    Slack review.
> 4. Copy the **Bot User OAuth Token** (`xoxb-…`) into `.env` as
>    `SLACK_SHARED_BOT_TOKEN`.
>
> On boot the gateway seeds `slack:token:shared` from `SLACK_SHARED_BOT_TOKEN`
> and `SLACK_SHARED_USER_TOKEN` (only if absent — rotation-safe), mirroring the
> Drive `google:shared` seed. Token rotation is **off by default**, so the tokens
> do not expire — no refresh logic required. The Slack tools always resolve this
> shared identity (`_SLACK_SHARED_USER`), just as the Drive tools resolve
> `_GOOGLE_SHARED_USER`.
>
> Add `SLACK_SHARED_USER_TOKEN` (`xoxp-…`, scope `search:read`) alongside the bot
> token so `slack-search-messages` works — `search.messages` rejects bot tokens.
> Both are Fernet-encrypted at rest, so `SLACK_TOKEN_ENCRYPTION_KEY` must be set
> whenever a shared token is provisioned.
>
> The current implementation uses shared workspace tokens (bot + user). A per-user
> 3-legged OAuth flow is not exposed today; if a tool must act as a specific user,
> provision that user's `xoxp-` token via `SLACK_SHARED_USER_TOKEN`.

---

## Security posture

Audited (latest run, this codebase):

- **`pip-audit`** → 0 known dependency vulnerabilities
- **`bandit`** static analysis → **0 findings** (the few B105 false positives on OAuth URL / token-key constants are suppressed with documented `# nosec` lines)
- A **dedicated security suite** (in the 257-test run) — the Confused Deputy proof, `verify=True` (TLS) assertions on every outbound HTTP client, log-masking, security headers, and the strict origin allowlist

Built-in defenses:

- **OAuth 2.1 + RFC 9728** protected-resource discovery; **RS256** JWT validation with JWKS TTL cache
- **Dynamic Client Registration (RFC 7591)**, triggered on demand inside `/oauth/authorize` when `client_id` is a metadata URL
- **Fernet** token encryption at rest, per-provider keys
- **OriginGuard** (strict origin allowlist on `/mcp`), **SecurityHeaders** (HSTS, nosniff), restricted **CORS**
- **SensitiveDataFilter** masks tokens in structured logs; **OpenTelemetry** traces (FastAPI + httpx auto-instrumented, OTLP) stamp the request log event with trace-id (broader log correlation is on the roadmap below)
- CI runs `ruff`, `pytest`, `bandit` + `pip-audit` on every pull request

---

## Quick start

```bash
just deps        # uv sync
just docker-up   # Keycloak + Redis
just dev         # uvicorn --reload
```

Gateway → http://localhost:8000 · MCP → http://localhost:8000/mcp/ · Keycloak → http://localhost:8080

```bash
# Obtain an access token from your IdP using authorization_code + PKCE.
# The gateway's /oauth/authorize endpoint enforces PKCE and state.
# For a local smoke test you can use client_credentials instead:
TOKEN=$(curl -s -X POST http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mcp-test \
  -d client_secret=local-dev-only-not-secret | jq -r .access_token)

curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":1,
       "params":{"name":"drive-search-files","arguments":{"full_text":"contract","max_results":10}}}'
```

If you obtain tokens through the gateway's `/oauth/authorize` endpoint, the following constraints apply:

> **OAuth 2.1 constraints.** The gateway's `/oauth/authorize` requires
> `code_challenge`/`code_challenge_method=S256` (PKCE), a `state` parameter, and a
> `redirect_uri`. For dynamically registered clients (`client_id` is a metadata URL)
> the redirect URI is validated against the metadata; pre-registered clients are
> validated by the upstream identity provider. Implicit and password grants are not
> supported.

### Smoke test the whole MCP flow (`test-api.sh`)

`app/test-api.sh` (at the `app/` submodule root) drives the full Streamable-HTTP handshake against a
running stack — health → `initialize` → `notifications/initialized` → `tools/list` →
`drive-list-recent` + `drive-search-files` calls → `prompts/list` → `prompts/get
drive-find-document`. It fetches its own Bearer token; pick one of two credential modes:

```bash
# Run from the app/ submodule root. Use bash (the script needs arrays/herestrings + `set -euo pipefail`).
CLIENT_ID=mcp-test CLIENT_SECRET=local-dev-only-not-secret bash test-api.sh  # client_credentials
TOKEN=eyJ...    bash test-api.sh   # bring your own JWT
```

| Mode | Env vars | Token carries | What you exercise |
|---|---|---|---|
| Service account | `CLIENT_ID=mcp-test CLIENT_SECRET=…` | **no** drive/slack roles | auth + routing only — tool/prompt lists come back **empty** |
| Bring your own | `TOKEN=…` | whatever you minted | — |

Notes:

- The `client_credentials` mode uses the **`mcp-test`** client (default secret `local-dev-only-not-secret`).
- The password grant has been removed because OAuth 2.1 no longer allows it. To test with a
  user-scoped token, obtain one from your IdP's authorization-code flow with PKCE and pass
  it via `TOKEN=...`.
- On the **host**, the issuer is `localhost:8080` (the stack pins `KC_HOSTNAME`); the script
  defaults to it. Override with `OAUTH_ISSUER_URL=` only if your gateway expects a different one.
- The Drive tool calls (steps 5–6) hit real Google Drive and need `GOOGLE_SHARED_REFRESH_TOKEN`
  provisioned; without it they return an upstream auth error, which still proves routing works.

### Seed users & access (local RBAC)

The local Keycloak realm (`mcp-gateway`) is seeded with three test users; passwords
and roles are defined in `compose/local/keycloak/realm.json`. Access to each
integration's MCP tools is gated by a per-client role — `drive-user` unlocks the
Drive tools, `slack-user` unlocks the Slack tools. A user only sees the tools their
roles grant.

| User | Roles | Drive tools | Slack tools |
|---|---|---|---|
| `june` | `drive-user` | ✅ | ❌ |
| `rayray` | `drive-user`, `slack-user` | ✅ | ✅ |
| `jasmine` | `slack-user` | ❌ | ✅ |

```bash
# User-scoped tokens must be obtained via authorization_code + PKCE (browser flow).
# For a non-interactive smoke test, use client_credentials instead:
TOKEN=$(curl -s -X POST http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mcp-test \
  -d client_secret=local-dev-only-not-secret | jq -r .access_token)
```

> Seeded from `compose/local/keycloak/realm.json` (and `seed_rbac.py`). Edit those to
> change the roster, then re-run `just docker-up`.

---

## Required configuration

Copy `.env.example` to `.env` and fill at least the values marked **required**. The
application aborts startup if `REDIS_URL` is missing.

| Variable | Required | Purpose |
|---|---|---|
| `REDIS_URL` | **yes** | Redis/Valkey connection string (e.g. `redis://localhost:6379`) |
| `OAUTH_ISSUER_URL` | **yes** | OpenID issuer that signs the downstream JWTs |
| `OAUTH_EXPECTED_AUDIENCE` | **yes** | Audience the gateway expects in the JWT (default matches local Keycloak) |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | when Drive enabled | Fernet key for the shared Google refresh token |
| `GOOGLE_CLIENT_ID` | when Drive enabled | OAuth client ID used to refresh the shared token |
| `GOOGLE_CLIENT_SECRET` | when Drive enabled | OAuth client secret used to refresh the shared token |
| `GOOGLE_SHARED_REFRESH_TOKEN` | when Drive enabled | Refresh token from `gcloud` (see Drive provisioning above) |
| `SLACK_TOKEN_ENCRYPTION_KEY` | when Slack enabled | Fernet key for shared Slack tokens |
| `SLACK_SHARED_BOT_TOKEN` | when Slack enabled | `xoxb-` token for `slack-send-message` |
| `SLACK_SHARED_USER_TOKEN` | for Slack search | `xoxp-` token for `slack-search-messages` |
| `SLACK_SIGNING_SECRET` | for webhooks | Verifies inbound Slack webhook HMAC |

---

## Production

For production deployments use `docker-compose.production.yml`. It differs from the local
stack in a few important ways:

- No `env_file` — every setting is injected through the environment.
- Required variables abort startup if unset (`${VAR:?...}`).
- Valkey persists data to a Docker volume (`valkey_data`).
- Async job exports are persisted to `/data/exports` (`exports_data`).
- OpenTelemetry is enabled through the `/start` script.

```bash
# example — set the required variables first
export OAUTH_ISSUER_URL=https://auth.example.com/realms/mcp-gateway
export OAUTH_EXPECTED_AUDIENCE=https://gateway.example.com/mcp/
export GATEWAY_BASE_URL=https://gateway.example.com
export OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example.com:4318
export REDIS_URL=redis://valkey:6379

docker compose -f docker-compose.production.yml up -d
```

See `.env.example` for the full list of tunables.

---

## Extensibility — add an integration in one folder

Every upstream implements one contract:

```python
# app/integrations/base.py
class UpstreamProvider(ABC):
    @abstractmethod
    async def get_valid_token(self, user_id: str) -> str: ...
```

Drop in `app/integrations/{provider}/` with `{provider}_client.py`, `token_store.py`,
`tools.py`, and `constants.py`; wire its tool registry into `app/mcp/server.py` and add config
keys — done. The same dual-OAuth, encryption, and rate-limit guarantees apply automatically.
HubSpot is the next planned provider.

---

## Engineering decisions (the short version)

| Decision | Choice | Because |
|---|---|---|
| State backend | **Redis** (`Store` protocol abstracts it; `InMemoryStore` for tests) | Horizontal scale, atomic Lua, native Streams |
| Auth | **OAuth 2.1 + RFC 9728**, not API keys | Interoperable, replay-resistant, audited spec |
| Trust model | **Two separate OAuth flows** | Confused-Deputy prevention + scope isolation |
| Token storage | **Fernet** authenticated encryption | Defense in depth; tamper-evident |
| Rate limiting | **Fixed-window counter** in Lua | Atomic (`INCR`+`PEXPIRE`), race-free under concurrency |
| Usage tracking | **Redis Streams** | Real-time queryable, consumer groups, retention |

---

## Quality

- **257 tests** passing · **93%** coverage (`respx`-mocked HTTP, security regression suite) — see [`COVERAGE.md`](COVERAGE.md)
- **Ruff** lint + format clean (`E,F,I,N,W,UP`, line-length 120)
- Python **3.13**, `uv` package manager
- `just ci` runs lint + tests + coverage locally; `just security` runs the scanners

```bash
just test       # pytest
just test-cov   # + coverage
just lint       # ruff check + format
just security   # bandit + pip-audit
just ci         # lint + test-cov
```

---

## Tech stack

<p>
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python_3.13-3776AB?logo=python&logoColor=white">
  <img alt="Redis" src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white">
  <img alt="Keycloak" src="https://img.shields.io/badge/Keycloak-4D4D4D?logo=keycloak&logoColor=white">
  <img alt="Google Drive" src="https://img.shields.io/badge/Google_Drive-4285F4?logo=googledrive&logoColor=white">
  <img alt="Slack" src="https://img.shields.io/badge/Slack-4A154B?logo=slack&logoColor=white">
  <img alt="OpenTelemetry" src="https://img.shields.io/badge/OpenTelemetry-000000?logo=opentelemetry&logoColor=white">
  <img alt="Pydantic" src="https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white">
</p>

Also: **httpx** + **tenacity** (resilient upstream calls) · **PyJWT** (RS256/JWKS) · **cryptography** (Fernet) · **tiktoken** (token counting) · **structlog** (JSON logs).

---

## Observability — necessary improvements

The goal is to **follow a user's journey end-to-end** — both the requests that
succeed and the ones that fail. We have two halves of the picture, and they are
not yet joined.

### What already works

- **Structured request log.** The middleware emits one JSON event per request
  (`method`, `path`, `status`, `duration_ms`, `request_id`, `trace_id`,
  `span_id`), and a sensitive-data filter scrubs bearer/Slack/refresh tokens.
- **OpenTelemetry is wired and running.** The containers start under
  `opentelemetry-instrument` (`compose/*/fastapi/start`), with FastAPI and httpx
  auto-instrumentation and an OTLP/HTTP exporter. This means, for free:
  - a **server span per request**,
  - a **client span per upstream call** (Drive/Slack) carrying the upstream
    status and latency — so "what did the upstream do" is already captured *in
    traces*, even though the clients log nothing,
  - `trace_id`/`span_id` already stamped onto the request log event, so that one
    line is trace-correlated today.

So the upstream-visibility and request-correlation gaps are largely solved **at
the trace layer**. The work left is to make the rest of the journey — identity,
the tool that ran, logical failures, and the scattered logs — correlate too.

### What still needs adjusting, even with OTel on

OTel does not magically enrich anything (it is a delivery mechanism, not a
decision about *what* to record). These remain to be done:

1. **Enrich the span with journey context.** The server span exists but is bare.
   Grab `get_current_span()` and set `user.id`, `mcp.tool`, `mcp.provider`,
   `scopes`, `auth.result`. Without these, traces show *that* a request happened,
   never *who* did *what*.
2. **Mark logical failures on the span.** MCP errors return as a JSON-RPC error
   inside an HTTP `200`, so neither the status code nor the auto-span reflects
   them. Tool handlers must call `span.record_exception(...)` +
   `span.set_status(ERROR)` so a failed tool call shows up as an error trace
   despite the 200.
3. **Make auth failures observable.** `AccessGuard` returns `401` before the
   request-logging middleware runs, so rejected requests produce **zero log
   lines**. Set `auth.result`/error status on the span *and* emit a log event on
   every `401` with a reason (`no_bearer`, `invalid_token`, validation class).
4. **Correlate the scattered logs.** Usage, rate-limiter, job-worker, and
   Slack-OAuth-callback logs carry no `trace_id`/`user.id`, so they can't be
   joined to the request. Turn on the distro's log correlation
   (`OTEL_PYTHON_LOG_CORRELATION=true`) to auto-stamp `otelTraceID`/`otelSpanID`
   onto every log record — one env var, no call-site changes.
5. **Record the success paths, not just failures.** Rate-limit blocks, completed
   export jobs, and successful OAuth callbacks log only on failure today; add the
   success side as span events/attributes so the happy path is queryable too.

Net effect: every request becomes one trace that carries identity, the
tool/integration touched, the upstream result, and any error — with all logs
correlated to it — for both the journeys that succeed and the ones that fail.

## License

MIT
