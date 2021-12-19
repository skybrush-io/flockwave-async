from functools import partial, wraps
from inspect import iscoroutine, iscoroutinefunction
from time import sleep as sleep_sync
from trio import sleep
from typing import Any, Awaitable, Callable, Optional, Union, TypeVar, overload

__all__ = ("delayed",)

T = TypeVar("T")


def _identity(obj: Any) -> Any:
    """Identity function that returns its input argument."""
    return obj


def delayed(
    seconds: float,
    fn: Optional[Union[Callable[..., T], Callable[..., Awaitable[T]]]] = None,
    *,
    ensure_async: bool = False
) -> Union[Callable[..., T], Callable[..., Awaitable[T]]]:
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

    elif iscoroutine(fn):

        async def decorated():
            await sleep(seconds)
            return await fn

        decorated = decorated()

    elif ensure_async:

        async def decorated(*args, **kwds):
            await sleep(seconds)
            return fn(*args, **kwds)

    else:

        def decorated(*args, **kwds):
            sleep_sync(seconds)
            return fn(*args, **kwds)

    return decorated
