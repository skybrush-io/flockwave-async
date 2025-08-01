from collections.abc import Mapping
from functools import partial
from anyio import create_task_group
from typing import Awaitable, Callable, TypeVar

__all__ = ("race",)

T = TypeVar("T")
T2 = TypeVar("T2")


async def race(funcs: Mapping[str, Callable[[], Awaitable[T]]]) -> tuple[str, T]:
    """Run multiple async functions concurrently and wait for at least one of
    them to complete. Return the key corresponding to the function and the
    result of the function as well.

    Raises:
        ExceptionGroup: when an exception happens in one of the functions
    """
    holder: list[tuple[str, T]] = []

    async with create_task_group() as tg:
        cancel = tg.cancel_scope.cancel
        for key, func in funcs.items():
            set_result = partial(_cancel_and_set_result, cancel, holder, key)
            tg.start_soon(_wait_and_call, func, set_result)

    return holder[0]


def _cancel_and_set_result(
    cancel: Callable[[], None], holder: list[tuple[str, T]], key: str, value: T
) -> None:
    holder.append((key, value))
    cancel()


async def _wait_and_call(f1: Callable[[], Awaitable[T]], f2: Callable[[T], T2]) -> T2:
    """Call an async function f1() and wait for its result. Call synchronous
    function `f2()` with the result of `f1()` when `f1()` returns.

    Returns:
        the return value of f2
    """
    result = await f1()
    return f2(result)
