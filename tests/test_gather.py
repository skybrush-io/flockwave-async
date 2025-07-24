from exceptiongroup import ExceptionGroup

import pytest
import trio

from flockwave.concurrency.gather import gather


async def async_add(x, y):
    await trio.sleep(0.01)
    return x + y


async def async_add_slow(x, y):
    await trio.sleep(1)
    return x + y


async def async_raise(exc):
    await trio.sleep(0.01)
    raise exc


async def append_slow(x):
    await trio.sleep(1)
    x.append(True)
    return 0


async def test_gather_sequence_success(autojump_clock):
    marker = []
    funcs = [
        lambda: async_add(1, 2),
        lambda: async_add_slow(3, 4),
        lambda: async_add(5, 6),
        lambda: append_slow(marker),
    ]
    results = await gather(funcs)
    assert results == [3, 7, 11, 0]
    assert marker == [True]  # Ensure slow function was also executed


async def test_gather_mapping_success(autojump_clock):
    funcs = {
        "a": lambda: async_add(1, 2),
        "b": lambda: async_add_slow(3, 4),
        "c": lambda: async_add(5, 6),
    }
    results = await gather(funcs)
    assert results == {"a": 3, "b": 7, "c": 11}


async def test_gather_sequence_exception(autojump_clock):
    marker = []
    funcs = [
        lambda: async_add(1, 2),
        lambda: async_raise(ValueError("fail")),
        lambda: async_add(5, 6),
        lambda: append_slow(marker),
    ]
    with pytest.raises(ExceptionGroup):
        await gather(funcs)
    assert marker == []  # Ensure slow function was not executed


async def test_gather_mapping_exception(autojump_clock):
    funcs = {
        "a": lambda: async_add(1, 2),
        "b": lambda: async_raise(KeyError("fail")),
        "c": lambda: async_add(5, 6),
    }
    with pytest.raises(ExceptionGroup):
        await gather(funcs)


async def test_gather_invalid_type(autojump_clock):
    with pytest.raises(TypeError):
        await gather(object())  # type: ignore
