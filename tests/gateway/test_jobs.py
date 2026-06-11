import pytest
from fakeredis.aioredis import FakeRedis

from app.gateway.jobs import (
    JOBS_STREAM,
    enqueue_export_job,
    ensure_group,
    job_owner,
    read_result,
)


@pytest.fixture
def redis():
    return FakeRedis(decode_responses=True)


async def test_enqueue_writes_stream_entry_and_owner_key(redis):
    job_id = await enqueue_export_job(redis, "u1", "file-abc", "pdf")

    assert isinstance(job_id, str) and job_id
    assert await job_owner(redis, job_id) == "u1"

    entries = await redis.xrange(JOBS_STREAM)
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    assert fields["job_id"] == job_id
    assert fields["user_id"] == "u1"
    assert fields["file_id"] == "file-abc"
    assert fields["format"] == "pdf"
    assert float(fields["ts"]) > 0


async def test_job_owner_missing_returns_none(redis):
    assert await job_owner(redis, "nope") is None


async def test_read_result_returns_published_record(redis):
    await redis.xadd("results:j1", {"status": "completed", "size_bytes": "42"})
    result = await read_result(redis, "j1", timeout_ms=200)
    assert result["status"] == "completed"
    assert result["size_bytes"] == "42"


async def test_read_result_timeout_returns_none(redis):
    result = await read_result(redis, "absent", timeout_ms=200)
    assert result is None


async def test_ensure_group_is_idempotent(redis):
    await ensure_group(redis)
    await ensure_group(redis)
    info = await redis.xinfo_groups(JOBS_STREAM)
    assert any(g["name"] == "exporters" for g in info)
