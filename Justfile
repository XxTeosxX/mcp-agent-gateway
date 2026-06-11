# Developer Experience Commands

default:
    @just --list

# Install dependencies
deps:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Installing dependencies..."
    uv sync
    echo "✓ Dependencies installed"

# Start development server with reload
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Starting development server on http://localhost:8000"
    echo "Press Ctrl+C to stop"
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
test:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Running tests..."
    uv run pytest -v
    echo "✓ All tests passed"

# Run tests with coverage report
test-cov:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Running tests with coverage..."
    uv run pytest --cov=app --cov-report=term-missing --cov-report=html
    echo "✓ Coverage report generated"
    echo "Open htmlcov/index.html for detailed report"

# Lint and format code
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Running linter..."
    uv run ruff check .
    echo "Running formatter..."
    uv run ruff format .
    echo "✓ Code is clean"

# Run full CI pipeline locally (lint + test + coverage)
ci: lint test-cov
    @echo "✓ CI pipeline passed"

# Start Docker services (Keycloak + Redis)
docker-up:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Starting Docker services..."
    docker compose -f docker-compose.local.yml up -d
    echo "✓ Services started"
    echo "Keycloak: http://localhost:8080 (admin/admin)"
    echo "Redis: localhost:6379"

# Stop Docker services
docker-down:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Stopping Docker services..."
    docker compose -f docker-compose.local.yml down
    echo "✓ Services stopped"

# Clean up (remove .venv, __pycache__, etc)
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Cleaning up..."
    rm -rf .venv
    rm -rf htmlcov
    rm -rf .pytest_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    echo "✓ Cleanup complete"

# Show help
help:
    @just --list

# Run security scanners (bandit + pip-audit)
security:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Running bandit (static analysis)..."
    uv run bandit -r app/ -s B101 -ll
    echo "Running pip-audit (dependency vulnerabilities)..."
    uv run pip-audit
    echo "✓ Security scans passed"

# Generate API documentation
docs:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Generating OpenAPI schema..."
    uv run python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
    echo "✓ OpenAPI schema saved to openapi.json"

# Check if all services are healthy
health:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Checking service health..."
    echo -n "Redis: "
    if docker compose -f docker-compose.local.yml exec -T redis redis-cli ping | grep -q PONG; then
        echo "✓ OK"
    else
        echo "✗ FAILED"
    fi
    echo -n "Keycloak: "
    if curl -s -f http://localhost:8080/health/ready > /dev/null; then
        echo "✓ OK"
    else
        echo "✗ FAILED"
    fi
    echo -n "Gateway: "
    if curl -s -f http://localhost:8000/health > /dev/null; then
        echo "✓ OK"
    else
        echo "✗ FAILED"
    fi
