from functools import partial
from trio import open_nursery
from typing import Awaitable, Callable, Dict, List, Tuple, TypeVar

__all__ = ("race",)

T = TypeVar("T")
T2 = TypeVar("T2")


async def race(funcs: Dict[str, Callable[[], T]]) -> Tuple[str, T]:
    """Run multiple async functions concurrently and wait for at least one of
    them to complete. Return the key corresponding to the function and the
    result of the function as well.
    """
    holder: List[Tuple[str, T]] = []

    async with open_nursery() as nursery:
        cancel = nursery.cancel_scope.cancel
        for key, func in funcs.items():
            set_result = partial(_cancel_and_set_result, cancel, holder, key)
            nursery.start_soon(_wait_and_call, func, set_result)

    return holder[0]


def _cancel_and_set_result(
    cancel: Callable[[], None], holder: List[Tuple[str, T]], key: str, value: T
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
