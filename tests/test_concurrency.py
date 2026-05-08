from pytest import raises
from trio import TooSlowError, fail_after, sleep

from flockwave.concurrency import delayed, delayed_sync, race


async def test_delayed_sync():
    def sync_func(a: int) -> int:
        return a + 5

    with raises(ValueError):
        delayed(-3, sync_func)

    with raises(ValueError):
        delayed_sync(-3, sync_func)

    assert delayed(0, sync_func) is not sync_func
    assert delayed_sync(0, sync_func) is sync_func

    delayed_sync_func = delayed(0.005, sync_func)
    assert delayed_sync_func is not sync_func

    delayed_result = await delayed_sync_func(42)
    assert delayed_result == sync_func(42)


async def test_delayed_async(nursery, autojump_clock):
    async def async_func(a: int) -> int:
        await sleep(1)
        return a + 5

    assert delayed(0, async_func) is async_func

    delayed_async_func = delayed(3, async_func)
    assert delayed_async_func is not async_func

    assert await delayed_async_func(42) == await async_func(42)

    with fail_after(2):
        assert await async_func(42) == 47

    with raises(TooSlowError):
        with fail_after(2):
            await delayed_async_func(42)


async def test_race(autojump_clock):
    terminated = []

    def make_func(x):
        nonlocal terminated

        def func():
            terminated.append(x)
            return x

        return func

    func1 = delayed(2, make_func(3))
    func2 = delayed(3, make_func(7))
    func3 = delayed(5, make_func(2))

    result = await race({"foo": func1, "bar": func2, "baz": func3})
    assert result == ("foo", 3)
    assert terminated == [3]
