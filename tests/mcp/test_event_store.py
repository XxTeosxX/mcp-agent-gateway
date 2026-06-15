import pytest
from mcp.types import JSONRPCRequest

from app.mcp.event_store import InMemoryEventStore


def _msg(method: str = "ping") -> JSONRPCRequest:
    return JSONRPCRequest(jsonrpc="2.0", id=1, method=method)


@pytest.fixture
def store():
    return InMemoryEventStore(max_events_per_stream=3)


async def test_store_event_returns_unique_ids(store):
    id1 = await store.store_event("stream-a", None)
    id2 = await store.store_event("stream-a", None)
    assert id1 != id2
    assert isinstance(id1, str)
    assert isinstance(id2, str)


async def test_replay_returns_stream_id(store):
    eid = await store.store_event("stream-x", None)
    result = await store.replay_events_after(eid, lambda _: None)
    assert result == "stream-x"


async def test_replay_unknown_event_returns_none(store):
    result = await store.replay_events_after("non-existent-id", lambda _: None)
    assert result is None


async def test_replay_delivers_events_after_cursor(store):
    e1 = await store.store_event("stream-b", _msg())
    e2 = await store.store_event("stream-b", _msg())
    e3 = await store.store_event("stream-b", _msg())

    delivered = []

    async def cb(msg):
        delivered.append(msg.event_id)

    await store.replay_events_after(e1, cb)
    assert delivered == [e2, e3]


async def test_replay_at_last_event_delivers_nothing(store):
    await store.store_event("stream-c", _msg())
    e2 = await store.store_event("stream-c", _msg())

    delivered = []

    async def cb(msg):
        delivered.append(msg.event_id)

    await store.replay_events_after(e2, cb)
    assert delivered == []


async def test_none_message_skipped_in_replay(store):
    # None messages are stored but not delivered to the callback
    e1 = await store.store_event("stream-n", None)
    await store.store_event("stream-n", None)  # should be skipped

    delivered = []

    async def cb(msg):
        delivered.append(msg.event_id)

    await store.replay_events_after(e1, cb)
    assert delivered == []


async def test_max_events_per_stream_evicts_oldest(store):
    # max_events_per_stream=3; 4th insert evicts the 1st
    e1 = await store.store_event("stream-d", None)
    await store.store_event("stream-d", None)
    await store.store_event("stream-d", None)
    await store.store_event("stream-d", None)  # evicts e1

    result = await store.replay_events_after(e1, lambda _: None)
    assert result is None  # e1 no longer in index


async def test_max_streams_evicts_oldest_stream():
    from app.mcp.event_store import _MAX_STREAMS

    store = InMemoryEventStore()
    for i in range(_MAX_STREAMS):
        await store.store_event(f"s-{i}", None)

    assert len(store.streams) == _MAX_STREAMS

    # One more stream causes eviction of s-0
    await store.store_event("s-overflow", None)
    assert len(store.streams) == _MAX_STREAMS
    assert "s-0" not in store.streams


async def test_events_isolated_across_streams(store):
    ea = await store.store_event("stream-a", _msg())
    await store.store_event("stream-b", _msg())
    await store.store_event("stream-b", _msg())

    delivered = []

    async def cb(msg):
        delivered.append(msg.event_id)

    # Replay from stream-a cursor — stream-b events must not appear
    await store.replay_events_after(ea, cb)
    assert delivered == []
