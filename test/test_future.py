from pytest import raises
from trio import CancelScope, WouldBlock, move_on_after, sleep

from flockwave.concurrency import Future, FutureCancelled
from flockwave.concurrency.future import FutureMap


def test_future_base_state():
    future: Future[int] = Future()

    assert not future.cancelled()
    assert not future.done()
    with raises(WouldBlock):
        future.result()
    with raises(WouldBlock):
        future.exception()


async def test_resolution_with_value(nursery):
    future: Future[int] = Future()

    async def resolver():
        future.set_result(42)

    nursery.start_soon(resolver)
    assert await future.wait() == 42

    assert not future.cancelled()
    assert future.done()
    assert future.result() == 42
    assert future.exception() is None


async def test_resolution_with_value_twice(nursery):
    future: Future[int] = Future()

    async def resolver(task_status):
        future.set_result(42)
        task_status.started()

    await nursery.start(resolver)

    with raises(RuntimeError):
        await nursery.start(resolver)


async def test_resolution_with_exception(nursery):
    future: Future[str] = Future()

    async def resolver():
        future.set_exception(ValueError("test"))

    nursery.start_soon(resolver)
    with raises(ValueError):
        await future.wait()

    assert not future.cancelled()
    assert future.done()
    assert isinstance(future.exception(), ValueError)
    assert "test" in str(future.exception())

    with raises(ValueError):
        future.result()


async def test_cancellation(nursery):
    future: Future[str] = Future()

    async def resolver(task_status):
        future.cancel()
        task_status.started()

    await nursery.start(resolver)

    assert future.cancelled()
    assert future.done()

    with raises(FutureCancelled):
        await future.wait()

    with raises(FutureCancelled):
        future.result()

    with raises(FutureCancelled):
        future.exception()


async def test_double_cancellation(nursery):
    future: Future[str] = Future()

    async def resolver(task_status):
        future.cancel()
        task_status.started()

    await nursery.start(resolver)

    assert future.cancelled()
    assert future.done()

    assert not future.cancel()

    assert future.cancelled()
    assert future.done()


async def test_trio_cancellation(autojump_clock, nursery):
    future: Future[int] = Future()

    async def resolver():
        await sleep(10)
        future.cancel()

    nursery.start_soon(resolver)
    with move_on_after(5) as scope:
        await future.wait()

    # At this point, the await was cancelled but the future is still
    # running
    assert scope.cancelled_caught

    assert not future.cancelled()
    assert not future.done()

    with raises(FutureCancelled):
        await future.wait()

    assert future.done()
    assert future.cancelled()


async def test_call_method(autojump_clock, nursery):
    future: Future[int] = Future()

    async def doubler(arg: int):
        await sleep(10)
        return 2 * arg

    async def resolver():
        await future.call(doubler, 21)

    nursery.start_soon(resolver)
    result = await future.wait()

    assert result == 42


async def test_call_method_that_raises(autojump_clock, nursery):
    future: Future[int] = Future()

    async def func_that_raises() -> int:
        await sleep(10)
        raise RuntimeError("test error")
        return 2

    async def resolver():
        await future.call(func_that_raises)

    nursery.start_soon(resolver)

    with raises(RuntimeError, match="test error"):
        await future.wait()


async def test_call_method_that_is_cancelled(autojump_clock, nursery):
    future: Future[int] = Future()

    async def func_that_will_be_cancelled() -> int:
        await sleep(10)
        return 42

    async def resolver(task_status):
        with CancelScope() as scope:
            task_status.started(scope)
            await future.call(func_that_will_be_cancelled)

    cancel_scope = await nursery.start(resolver)
    await sleep(5)
    cancel_scope.cancel()

    with raises(FutureCancelled):
        await future.wait()

    assert future.cancelled()


def test_future_map_base_state():
    map: FutureMap[int] = FutureMap()
    assert len(map) == 0


async def test_future_map_mapping_methods(nursery, autojump_clock):
    map: FutureMap[int] = FutureMap()

    async def doubler(value: int) -> int:
        await sleep(1)
        return value * 2

    async with map.new("foo") as f1:
        assert len(map) == 1
        assert map["foo"] is f1
        assert list(map) == ["foo"]

        async with map.new("bar") as f2, map.new("baz") as f3:
            assert len(map) == 3
            assert map["foo"] is f1
            assert map["bar"] is f2
            assert map["baz"] is f3
            assert sorted(map) == ["bar", "baz", "foo"]

            await f3.call(doubler, 3)
            await f2.call(doubler, 7)

        assert f3.result() == 6
        assert f2.result() == 14

        assert len(map) == 1
        assert map["foo"] is f1
        with raises(KeyError):
            map["bar"]
        with raises(KeyError):
            map["baz"]

        await f1.call(doubler, 11)

    assert len(map) == 0
    assert f1.result() == 22


async def test_future_map_double_id(nursery, autojump_clock):
    map: FutureMap[int] = FutureMap()

    async def doubler(value: int) -> int:
        await sleep(1)
        return value * 2

    with raises(FutureCancelled):
        async with map.new("foo") as f1:
            nursery.start_soon(f1.call, doubler, 3)
            assert len(map) == 1

            # Let the "doubler" function start
            await sleep(0.1)

            # Now create a new future, which cancels the doubler task that is
            # already in progress
            with raises(RuntimeError, match="already in progress"):
                async with map.new("foo", strict=True):
                    pass
