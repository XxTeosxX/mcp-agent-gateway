# Test coverage

**238 tests passing · 93% line coverage** (1309 statements, 89 uncovered).

Reproduce locally:

```bash
just test-cov          # or: uv run pytest --cov=app --cov-report=term-missing
```

The suite is fully hermetic — Redis is faked with `fakeredis`, all upstream HTTP
(Google Drive, Slack, Keycloak/JWKS) is mocked with `respx`/`httpx` — so no network,
no credentials, and no running stack are required.

## By module

| Module | Stmts | Miss | Cover |
|---|---:|---:|---:|
| `api/usage_router.py` | 28 | 0 | 100% |
| `api/webhooks_router.py` | 39 | 3 | 92% |
| `authorization/router.py` | 48 | 0 | 100% |
| `config.py` | 42 | 0 | 100% |
| `identity/client_registration/models.py` | 72 | 10 | 86% |
| `identity/client_registration/registrar.py` | 24 | 4 | 83% |
| `identity/client_registration/repository.py` | 12 | 0 | 100% |
| `identity/jwks_client.py` | 8 | 1 | 88% |
| `identity/protected_resource.py` | 7 | 0 | 100% |
| `identity/token_validator.py` | 28 | 18 | 36% |
| `integrations/base.py` | 2 | 2 | 0% |
| `integrations/google/drive_client.py` | 46 | 0 | 100% |
| `integrations/google/drive_query.py` | 18 | 0 | 100% |
| `integrations/google/job_tools.py` | 49 | 7 | 86% |
| `integrations/google/job_worker.py` | 70 | 8 | 89% |
| `integrations/google/jobs.py` | 28 | 1 | 96% |
| `integrations/google/prompts.py` | 12 | 0 | 100% |
| `integrations/google/token_store.py` | 43 | 1 | 98% |
| `integrations/google/tools.py` | 105 | 20 | 81% |
| `integrations/slack/signature.py` | 16 | 0 | 100% |
| `integrations/slack/slack_client.py` | 35 | 0 | 100% |
| `integrations/slack/token_store.py` | 31 | 0 | 100% |
| `integrations/slack/tools.py` | 75 | 1 | 99% |
| `logging.py` | 15 | 0 | 100% |
| `main.py` | 83 | 1 | 99% |
| `mcp/app.py` | 21 | 1 | 95% |
| `mcp/event_store.py` | 48 | 0 | 100% |
| `mcp/health.py` | 5 | 0 | 100% |
| `mcp/server.py` | 61 | 3 | 95% |
| `middleware/access_guard.py` | 39 | 0 | 100% |
| `middleware/origin_guard.py` | 12 | 0 | 100% |
| `middleware/rate_limiter.py` | 40 | 1 | 98% |
| `middleware/request_logger.py` | 19 | 2 | 89% |
| `middleware/security_headers.py` | 7 | 0 | 100% |
| `shared/context.py` | 3 | 0 | 100% |
| `shared/dependencies.py` | 13 | 2 | 85% |
| `shared/exceptions.py` | 6 | 0 | 100% |
| `shared/http_client.py` | 9 | 0 | 100% |
| `shared/redis.py` | 5 | 0 | 100% |
| `shared/store.py` | 44 | 3 | 93% |
| `shared/usage.py` | 37 | 0 | 100% |
| **TOTAL** | **1309** | **89** | **93%** |

## Notable gaps

- `identity/token_validator.py` (36%) — the RS256/JWKS happy path is exercised end-to-end
  through `AccessGuard` integration tests rather than in isolation; the uncovered lines are
  the network-fetch branch that the higher-level tests mock at the boundary.
- `integrations/base.py` (0%) — an abstract contract (`UpstreamProvider`); nothing to run.
- `integrations/google/tools.py` (81%) — uncovered lines are defensive error branches on
  malformed upstream payloads.
