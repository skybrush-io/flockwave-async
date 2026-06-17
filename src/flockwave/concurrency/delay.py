from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import iscoroutinefunction
from time import sleep as sleep_sync
from typing import ParamSpec, TypeVar, cast, overload

from anyio import sleep

__all__ = ("delayed", "delayed_sync")

P = ParamSpec("P")
T = TypeVar("T")


@overload
def delayed(
    seconds: float,
    fn: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]: ...


@overload
def delayed(
    seconds: float,
    fn: Callable[P, T],
) -> Callable[P, Awaitable[T]]: ...


def delayed(
    seconds: float,
    fn: Callable[P, T] | Callable[P, Awaitable[T]],
):
    """Decorator or decorator factory that delays the execution of a
    synchronous or asynchronous function with a given number of seconds.

    Parameters:
        seconds: the number of seconds to delay with. Negative numbers will
            throw an exception. Zero will return the input function without any
            modifications if it is already a coroutine-returning function; otherwise it
            will return the input function wrapped in an async function that returns an
            awaitable.
        fn: the function to delay. `None` to return a decorator that can be used to
            delay a function.

    Returns:
        the delayed function if `fn` is not `None`, otherwise a decorator that can be
        used to delay a function.
    """
    if seconds < 0:
        raise ValueError("delay must not be negative")

    if seconds == 0:
        if iscoroutinefunction(fn):
            return fn
        else:
            # We now know that fn is a synchronous function
            fn_sync = cast("Callable[P, T]", fn)

            @wraps(fn_sync)
            async def decorated(*args: P.args, **kwds: P.kwargs) -> T:
                return fn_sync(*args, **kwds)

            return decorated

    if iscoroutinefunction(fn):
        # We now know that fn is an asynchronous function
        fn = cast("Callable[P, Awaitable[T]]", fn)

        async def decorated(*args, **kwds) -> T:
            await sleep(seconds)
            return await fn(*args, **kwds)

    else:
        # We now know that fn is a synchronous function
        fn_sync = cast("Callable[P, T]", fn)

        async def decorated(*args, **kwds) -> T:
            await sleep(seconds)
            return fn_sync(*args, **kwds)

    return wraps(fn)(decorated)


def delayed_sync(
    seconds: float,
    fn: Callable[P, T],
):
    """Decorator or decorator factory that delays the execution of a synchronous
    function with a given number of seconds.

    Parameters:
        seconds: the number of seconds to delay with. Negative numbers will
            throw an exception. Zero will return the input function without any
            modifications.
        fn: the function to delay. `None` to return a decorator that can be used to
            delay a function.

    Returns:
        the delayed function if `fn` is not `None`, otherwise a decorator that can be
        used to delay a function.
    """
    if seconds < 0:
        raise ValueError("delay must not be negative")

    if seconds == 0:
        return fn

    @wraps(fn)
    def decorated(*args, **kwds) -> T:
        sleep_sync(seconds)
        return fn(*args, **kwds)

    return decorated
