import json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis

from app.integrations.google.drive_client import DriveClient
from app.integrations.google.job_worker import JobWorker
from app.integrations.google.jobs import enqueue_export_job, read_result
from app.shared.http_client import HttpClient
from app.shared.store import InMemoryStore


@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())


@pytest.fixture
async def stored_token(fernet):
    store = InMemoryStore()
    enc = fernet.encrypt(b"refresh").decode()
    await store.set(
        "u1",
        json.dumps(
            {
                "access_token": "valid-access-token",
                "refresh_token_enc": enc,
                "expires_at": time.time() + 3600,
            }
        ),
    )
    return store


@pytest.fixture
async def drive_client():
    dc = DriveClient(timeout=10.0, max_connections=10, max_keepalive=5, max_retries=3)
    yield dc
    await dc.close()


@pytest.fixture
async def http_client():
    hc = HttpClient()
    yield hc
    await hc.close()


@respx.mock
async def test_process_completed_writes_file_and_publishes(tmp_path, stored_token, fernet, drive_client, http_client):
    from app.integrations.google.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(200, content=b"%PDF fake")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    entries = await redis.xrange("jobs:drive_export")
    entry_id, fields = entries[0]

    worker = JobWorker(
        redis=redis,
        drive_client=drive_client,
        token_store=stored_token,
        fernet=fernet,
        http_client=http_client,
        client_id="test-client-id",
        client_secret="test-secret",
        export_dir=str(tmp_path),
    )
    await worker._process(entry_id, fields)

    result = await read_result(redis, job_id, timeout_ms=200)
    assert result["status"] == "completed"
    assert result["mime"] == "application/pdf"
    assert int(result["size_bytes"]) == len(b"%PDF fake")
    assert (tmp_path / f"{job_id}.pdf").read_bytes() == b"%PDF fake"
    pending = await redis.xpending("jobs:drive_export", "exporters")
    assert pending["pending"] == 0


@respx.mock
async def test_process_failed_publishes_failed_result(tmp_path, stored_token, fernet, drive_client, http_client):
    from app.integrations.google.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(500, content=b"boom")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    entry_id, fields = (await redis.xrange("jobs:drive_export"))[0]

    worker = JobWorker(
        redis=redis,
        drive_client=drive_client,
        token_store=stored_token,
        fernet=fernet,
        http_client=http_client,
        client_id="test-client-id",
        client_secret="test-secret",
        export_dir=str(tmp_path),
    )
    await worker._process(entry_id, fields)

    result = await read_result(redis, job_id, timeout_ms=200)
    assert result["status"] == "failed"
    assert "error" in result


@respx.mock
async def test_run_loop_consumes_and_publishes(tmp_path, stored_token, fernet, drive_client, http_client):
    import asyncio

    from app.integrations.google.jobs import ensure_group

    redis = FakeRedis(decode_responses=True)
    await ensure_group(redis)
    respx.get("https://www.googleapis.com/drive/v3/files/file-1/export").mock(
        return_value=httpx.Response(200, content=b"data")
    )
    job_id = await enqueue_export_job(redis, "u1", "file-1", "txt")

    worker = JobWorker(
        redis=redis,
        drive_client=drive_client,
        token_store=stored_token,
        fernet=fernet,
        http_client=http_client,
        client_id="test-client-id",
        client_secret="test-secret",
        export_dir=str(tmp_path),
    )
    task = asyncio.create_task(worker.run())
    try:
        result = await read_result(redis, job_id, timeout_ms=3000)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result["status"] == "completed"
    assert (tmp_path / f"{job_id}.txt").read_bytes() == b"data"
