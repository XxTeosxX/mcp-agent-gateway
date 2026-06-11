import json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis

from app.config import settings
from app.gateway.job_worker import JobWorker
from app.gateway.jobs import enqueue_export_job, read_result
from app.integrations.google.drive_client import drive_client
from app.shared.store import InMemoryStore, token_store


@pytest.fixture(autouse=True)
def _setup_singletons():
    drive_client.init()
    token_store.init(InMemoryStore())
    yield
    import asyncio

    asyncio.run(drive_client.close())


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    return key


@pytest.fixture
async def stored_token(encryption_key):
    enc = Fernet(settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode()).encrypt(b"refresh").decode()
    await token_store.get().set(
        "u1",
        json.dumps(
            {
                "access_token": "valid-access-token",
                "refresh_token_enc": enc,
                "expires_at": time.time() + 3600,
            }
        ),
    )


@respx.mock
async def test_process_completed_writes_file_and_publishes(tmp_path, stored_token):
    from app.gateway.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(200, content=b"%PDF fake")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    entries = await redis.xrange("jobs:drive_export")
    entry_id, fields = entries[0]

    worker = JobWorker(redis, export_dir=str(tmp_path))
    await worker._process(entry_id, fields)

    result = await read_result(redis, job_id, timeout_ms=200)
    assert result["status"] == "completed"
    assert result["mime"] == "application/pdf"
    assert int(result["size_bytes"]) == len(b"%PDF fake")
    assert (tmp_path / f"{job_id}.pdf").read_bytes() == b"%PDF fake"
    pending = await redis.xpending("jobs:drive_export", "exporters")
    assert pending["pending"] == 0


@respx.mock
async def test_process_failed_publishes_failed_result(tmp_path, stored_token):
    from app.gateway.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(500, content=b"boom")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    entry_id, fields = (await redis.xrange("jobs:drive_export"))[0]

    worker = JobWorker(redis, export_dir=str(tmp_path))
    await worker._process(entry_id, fields)

    result = await read_result(redis, job_id, timeout_ms=200)
    assert result["status"] == "failed"
    assert "error" in result


@respx.mock
async def test_run_loop_consumes_and_publishes(tmp_path, stored_token):
    import asyncio

    from app.gateway.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(200, content=b"data")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "txt")

    worker = JobWorker(redis, export_dir=str(tmp_path))
    task = asyncio.create_task(worker.run())
    try:
        result = await read_result(redis, job_id, timeout_ms=3000)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result["status"] == "completed"
    assert (tmp_path / f"{job_id}.txt").read_bytes() == b"data"
