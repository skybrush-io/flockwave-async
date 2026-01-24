from functools import partial, wraps
from inspect import iscoroutine, iscoroutinefunction
from time import sleep as sleep_sync
from typing import Any, Awaitable, Callable, Coroutine, ParamSpec, TypeVar, overload

from anyio import sleep

__all__ = ("delayed",)

P = ParamSpec("P")
T = TypeVar("T")
CR = TypeVar("CR", bound="Coroutine")


def _identity(obj: Any) -> Any:
    """Identity function that returns its input argument."""
    return obj


@overload
def delayed(
    seconds: float,
    fn: None = None,
    *,
    ensure_async: bool = False,
) -> Callable[[Callable[P, T] | CR], Callable[P, T] | CR]: ...


@overload
def delayed(
    seconds: float,
    fn: CR,
    *,
    ensure_async: bool = False,
) -> CR: ...


@overload
def delayed(
    seconds: float,
    fn: Callable[P, T] | Callable[P, Awaitable[T]],
    *,
    ensure_async: bool = False,
) -> Callable[P, T] | Callable[P, Awaitable[T]]: ...


def delayed(
    seconds: float,
    fn: Callable[P, T] | Callable[P, Awaitable[T]] | None = None,
    *,
    ensure_async: bool = False,
):
    """Decorator or decorator factory that delays the execution of a
    synchronous function, coroutine or coroutine-returning function with a
    given number of seconds.

    Parameters:
        seconds: the number of seconds to delay with. Negative numbers will
            throw an exception. Zero will return the identity function.
        fn: the function, coroutine or coroutine-returning function to delay
        ensure_async: when set to `True`, synchronous functions will automatically
            be converted to asynchronous before delaying them. This is needed
            if the delayed function is going to be executed in the async
            event loop because a synchronous function that sleeps will block
            the entire event loop.

    Returns:
        the delayed function, coroutine or coroutine-returning function
    """
    if seconds < 0:
        raise ValueError("delay must not be negative")

    if seconds == 0 and not ensure_async:
        return _identity if fn is None else fn

    if fn is None:
        return partial(delayed, seconds, ensure_async=ensure_async)

    if iscoroutinefunction(fn):

        @wraps(fn)
        async def decorated(*args, **kwds):
            await sleep(seconds)
            return await fn(*args, **kwds)

        return decorated

    if iscoroutine(fn):

        async def decorated():
            await sleep(seconds)
            return await fn

        return decorated()

    if ensure_async:

        async def decorated(*args, **kwds):
            await sleep(seconds)
            return fn(*args, **kwds)

        return decorated

    def decorated(*args, **kwds):
        sleep_sync(seconds)
        return fn(*args, **kwds)

    return decorated
