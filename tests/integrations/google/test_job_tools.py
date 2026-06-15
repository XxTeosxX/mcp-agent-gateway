import json

import pytest
from fakeredis.aioredis import FakeRedis

from app.integrations.google import job_tools
from app.integrations.google.jobs import enqueue_export_job, job_queue
from app.shared.context import current_user_id


@pytest.fixture
def redis():
    r = FakeRedis(decode_responses=True)
    job_queue.init(r)
    return r


async def test_export_tool_enqueues_and_returns_job_id(redis):
    token = current_user_id.set("u1")
    try:
        result = await job_tools.handle_drive_export_large_file({"file_id": "file-1", "format": "pdf"})
    finally:
        current_user_id.reset(token)

    assert result.isError is False
    body = json.loads(result.content[0].text)
    assert body["status"] == "queued"
    assert body["job_id"]
    assert await redis.xlen("jobs:drive_export") == 1


async def test_export_tool_rejects_unknown_format(redis):
    token = current_user_id.set("u1")
    try:
        result = await job_tools.handle_drive_export_large_file({"file_id": "file-1", "format": "xlsx"})
    finally:
        current_user_id.reset(token)

    assert result.isError is True
    assert "xlsx" in result.content[0].text


async def test_wait_rejects_non_owner(redis):
    job_id = await enqueue_export_job(redis, "owner-user", "file-1", "pdf")
    token = current_user_id.set("intruder")
    try:
        result = await job_tools.handle_wait_for_job({"job_id": job_id})
    finally:
        current_user_id.reset(token)

    assert result.isError is True
    assert result.content[0].text == "job not found"


async def test_wait_owner_pending_returns_pending(redis):
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    token = current_user_id.set("u1")
    try:
        result = await job_tools.handle_wait_for_job({"job_id": job_id, "timeout_seconds": 1})
    finally:
        current_user_id.reset(token)

    body = json.loads(result.content[0].text)
    assert body["status"] == "pending"


async def test_wait_owner_returns_result(redis):
    job_id = await enqueue_export_job(redis, "u1", "file-1", "pdf")
    await redis.xadd(f"results:{job_id}", {"status": "completed", "size_bytes": "9"})
    token = current_user_id.set("u1")
    try:
        result = await job_tools.handle_wait_for_job({"job_id": job_id, "timeout_seconds": 1})
    finally:
        current_user_id.reset(token)

    body = json.loads(result.content[0].text)
    assert body["status"] == "completed"
    assert body["size_bytes"] == "9"


def test_job_tools_and_registry_shape():
    assert {t.name for t in job_tools.JOB_TOOLS} == {
        "drive-export-large-file",
        "wait-for-job",
    }
    assert set(job_tools.JOB_REGISTRY) == {
        "drive-export-large-file",
        "wait-for-job",
    }
    for handler in job_tools.JOB_REGISTRY.values():
        assert hasattr(handler, "__wrapped__")
