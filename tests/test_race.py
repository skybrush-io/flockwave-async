from exceptiongroup import ExceptionGroup

import pytest
import trio

from flockwave.concurrency.race import race


async def test_race_returns_first_completed(autojump_clock):
    async def fast():
        await trio.sleep(0.1)
        return "fast"

    async def slow():
        await trio.sleep(1)
        return "slow"

    funcs = {"a": fast, "b": slow}
    key, result = await race(funcs)
    assert key == "a"
    assert result == "fast"


async def test_race_cancels_slow_function(autojump_clock):
    slow_executed = False

    async def fast():
        await trio.sleep(0.1)
        return "fast"

    async def slow():
        nonlocal slow_executed
        await trio.sleep(1)
        slow_executed = True
        return "slow"

    funcs = {"a": fast, "b": slow}
    await race(funcs)
    assert not slow_executed


async def test_race_with_single_function(autojump_clock):
    async def only():
        await trio.sleep(0.05)
        return "single"

    funcs = {"only": only}
    key, result = await race(funcs)
    assert key == "only"
    assert result == "single"


async def test_race_raises_exception_group(autojump_clock):
    async def ok():
        await trio.sleep(0.1)
        return "ok"

    async def fail():
        await trio.sleep(0.05)
        raise ValueError("fail")

    funcs = {"ok": ok, "fail": fail}
    with pytest.raises(ExceptionGroup):
        await race(funcs)


async def test_race_empty_mapping():
    with pytest.raises(IndexError):
        await race({})
