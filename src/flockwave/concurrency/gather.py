from anyio import create_task_group
from functools import partial
from operator import setitem
from typing import Awaitable, Callable, Mapping, Sequence, TypeVar, cast, overload

from .race import _wait_and_call

__all__ = ("gather",)

T = TypeVar("T")


@overload
async def gather(funcs: Sequence[Callable[[], Awaitable[T]]]) -> Sequence[T]: ...


@overload
async def gather(
    funcs: Mapping[str, Callable[[], Awaitable[T]]],
) -> Mapping[str, T]: ...


async def gather(
    funcs: Mapping[str, Callable[[], Awaitable[T]]]
    | Sequence[Callable[[], Awaitable[T]]],
) -> Mapping[str, T] | Sequence[T]:
    """Run multiple async functions concurrently and wait for all of them to
    complete. The results are collected in a list or mapping, depending on the
    format of the input argument.

    Raises:
        ExceptionGroup: when an exception happens in one of the functions
    """
    if isinstance(funcs, Mapping):
        return await _gather_map(funcs)
    elif isinstance(funcs, Sequence):
        return await _gather_seq(funcs)
    else:
        raise TypeError("funcs must be a Mapping or a Sequence of callables")


async def _gather_map(
    funcs: Mapping[str, Callable[[], Awaitable[T]]],
) -> Mapping[str, T]:
    result: dict[str, T] = {}

    async with create_task_group() as tg:
        for key, func in funcs.items():
            set_result = partial(setitem, result, key)
            tg.start_soon(_wait_and_call, func, set_result)

    return result


async def _gather_seq(
    funcs: Sequence[Callable[[], Awaitable[T]]],
) -> Sequence[T]:
    result: list[T | None] = [None] * len(funcs)

    async with create_task_group() as nursery:
        for index, func in enumerate(funcs):
            set_result = partial(setitem, result, index)
            nursery.start_soon(_wait_and_call, func, set_result)

    return cast(Sequence[T], result)
