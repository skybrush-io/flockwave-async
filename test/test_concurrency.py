from pytest import raises
from trio import fail_after, move_on_after, sleep, TooSlowError

from flockwave.concurrency import (
    aclosing,
    delayed,
    race,
)


async def test_aclosing(autojump_clock):
    async def wait():
        for i in range(100):
            await sleep(1)
            yield i

    items = []
    gen = wait()
    with move_on_after(4.5):
        async with aclosing(gen):
            async for item in gen:
                items.append(item)

    assert items == [0, 1, 2, 3]


def test_delayed_sync():
    def sync_func(a):
        return a + 5

    with raises(ValueError):
        delayed(-3)

    assert delayed(0)(sync_func) is sync_func
    assert delayed(0, sync_func) is sync_func  # type: ignore

    delayed_sync_func = delayed(0.005)(sync_func)
    assert delayed_sync_func is not sync_func

    assert delayed_sync_func(42) == sync_func(42)  # type: ignore


async def test_delayed_async(nursery, autojump_clock):
    async def async_func(a):
        await sleep(1)
        return a + 5

    assert delayed(0)(async_func) == async_func
    assert delayed(0, async_func) == async_func  # type: ignore

    delayed_async_func = delayed(3)(async_func)
    assert delayed_async_func is not async_func

    assert await delayed_async_func(42) == await async_func(42)  # type: ignore

    with fail_after(2):
        assert await async_func(42) == 47

    with raises(TooSlowError):
        with fail_after(2):
            await delayed_async_func(42)  # type: ignore


async def test_delayed_coroutine(nursery, autojump_clock):
    async def async_func(a):
        await sleep(1)
        return a + 5

    coro = async_func(6)
    delayed_coro = delayed(3)(coro)
    assert delayed_coro is not coro

    assert await delayed_coro == 11  # type: ignore


async def test_race(autojump_clock):
    terminated = []

    def make_func(x):
        nonlocal terminated

        def func():
            terminated.append(x)
            return x

        return func

    func1 = delayed(2, make_func(3), ensure_async=True)
    func2 = delayed(3, make_func(7), ensure_async=True)
    func3 = delayed(5, make_func(2), ensure_async=True)

    result = await race({"foo": func1, "bar": func2, "baz": func3})
    assert result == ("foo", 3)
    assert terminated == [3]
