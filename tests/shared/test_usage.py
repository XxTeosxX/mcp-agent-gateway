import pytest
from fakeredis.aioredis import FakeRedis
from mcp import types

from app.shared.context import current_user_id
from app.shared.usage import (
    count_tokens,
    record_usage,
    track_usage,
    usage_recorder,
)


@pytest.fixture
def redis():
    return FakeRedis(decode_responses=True)


def _result(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def test_count_tokens_positive():
    assert count_tokens("hello world") > 0
    assert count_tokens("") == 0


async def test_record_usage_appends_entry(redis):
    await record_usage(redis, "u1", "drive-search-files", 10, 20)
    entries = await redis.xrange("usage:u1")
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    assert fields["tool"] == "drive-search-files"
    assert fields["in_tokens"] == "10"
    assert fields["out_tokens"] == "20"
    assert float(fields["ts"]) > 0


async def test_track_usage_records_in_and_out(redis):
    usage_recorder.init(redis)
    token = current_user_id.set("u1")
    try:

        @track_usage("dummy-tool")
        async def handler(arguments):
            return _result("some output text")

        result = await handler({"query": "hello there"})
    finally:
        current_user_id.reset(token)

    assert result.content[0].text == "some output text"
    entries = await redis.xrange("usage:u1")
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    assert fields["tool"] == "dummy-tool"
    assert int(fields["in_tokens"]) > 0
    assert int(fields["out_tokens"]) > 0


async def test_track_usage_fail_open_when_no_redis():
    usage_recorder.init(None)
    token = current_user_id.set("u1")
    try:

        @track_usage("dummy-tool")
        async def handler(arguments):
            return _result("output")

        result = await handler({})
    finally:
        current_user_id.reset(token)

    assert result.content[0].text == "output"


async def test_track_usage_fail_open_when_xadd_raises():
    class BrokenRedis:
        async def xadd(self, *args, **kwargs):
            raise RuntimeError("redis down")

    usage_recorder.init(BrokenRedis())
    token = current_user_id.set("u1")
    try:

        @track_usage("dummy-tool")
        async def handler(arguments):
            return _result("output")

        result = await handler({})
    finally:
        current_user_id.reset(token)

    assert result.content[0].text == "output"


async def test_track_usage_skips_when_no_user(redis):
    usage_recorder.init(redis)
    token = current_user_id.set("")
    try:

        @track_usage("dummy-tool")
        async def handler(arguments):
            return _result("output")

        result = await handler({})
    finally:
        current_user_id.reset(token)

    assert result.content[0].text == "output"
    assert await redis.xrange("usage:") == []
