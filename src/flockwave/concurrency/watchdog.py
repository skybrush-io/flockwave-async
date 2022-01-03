from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from trio import (
    CancelScope,
    Nursery,
    TASK_STATUS_IGNORED,
    TooSlowError,
    current_time,
    open_nursery,
    sleep,
)
from typing import AsyncIterator, Callable, Iterator, Optional

__all__ = ("Watchdog",)


class Watchdog:
    """Object that provides a `notify()` method and requires other tasks to
    call this method periodically while the watchdog is active.

    May call a pre-defined method when `notify()` was not called in time.
    Raises TooSlowError_ if no callback is defined.
    """

    on_expired: Optional[Callable[[], Optional[float]]]
    timeout: float

    _last_notified: float

    def __init__(
        self, timeout: float, on_expired: Optional[Callable[[], Optional[float]]] = None
    ):
        """Constructor.

        Parameters:
            timeout: maximum number of seconds that may pass between consecutive
                invocations of `notify()`
            on_expired: a callback that will be called by the watchdog when the
                `notify()` method was to invoked in time while the watchdog was
                active. The callback must return `None` to keep the watchdog
                running with the same timeout, a positive number to adjust the
                timeout of thw watchdog until normal operation is resumed,
                or zero or a negative number to stop the watchdog entirely.
        """
        self.on_expired = on_expired
        self.timeout = timeout
        self.notify()  # make sure that _last_notified has a valid value

    def notify(self) -> None:
        """Function that must be called regularly while the watchdog is
        being used. Has no effect when called when the watchdog is inactive.
        """
        self._last_notified = current_time()

    def start_soon(self, nursery: Nursery) -> CancelScope:
        """Starts the background task of the watchdog as soon as possible.

        Note that this function will return earlier and _not_ wait for the
        watchdog to be started. If you want to be sure that the watchdog is
        already active, use `start()` instead.

        Returns:
            a cancel scope that can be used to stop the watchdog.
        """
        scope = CancelScope()
        nursery.start_soon(self._watch, scope)
        return scope

    async def start(self, nursery: Nursery) -> CancelScope:
        """Starts the background task of the watchdog and waits for it to be
        started.

        Returns:
            a cancel scope that can be used to stop the watchdog.
        """
        scope = CancelScope()
        await nursery.start(self._watch, scope)
        return scope

    @asynccontextmanager
    async def use(self, nursery: Nursery) -> AsyncIterator["Watchdog"]:
        """Asynchronous context manager that starts the watchdog and waits for
        it to start up, then enters the context. Stops the watchdog automatically
        when exiting the context.

        Yields:
            the watchdog itself
        """
        scope = await self.start(nursery)
        try:
            yield self
        finally:
            scope.cancel()

    @contextmanager
    def use_soon(self, nursery: Nursery) -> Iterator["Watchdog"]:
        """Context manager that starts the watchdog (but does not wait for
        it to start up), then enters the context. Stops the watchdog
        automatically when exiting the context.

        Yields:
            the watchdog itself
        """
        scope = self.start_soon(nursery)
        try:
            yield self
        finally:
            scope.cancel()

    async def _watch(
        self, cancel_scope: CancelScope, *, task_status=TASK_STATUS_IGNORED
    ) -> None:
        with cancel_scope:
            self.notify()  # make sure that _last_notified has a valid value
            task_status.started()
            deadline = current_time() + self.timeout
            while True:
                to_wait = deadline - current_time()
                if to_wait > 0:
                    await sleep(to_wait)
                    deadline = self._last_notified + self.timeout
                else:
                    if self.on_expired:
                        next_timeout = self.on_expired()
                    else:
                        raise TooSlowError("watchdog expired")
                    if next_timeout is None:
                        next_timeout = self.timeout
                    if next_timeout <= 0:
                        return
                    deadline = current_time() + next_timeout


@asynccontextmanager
async def use_watchdog(
    timeout: float, on_expired: Optional[Callable[[], Optional[float]]] = None
) -> AsyncIterator[Watchdog]:
    """Simplified interface to creating and running a watchdog."""
    watchdog = Watchdog(timeout, on_expired)
    async with open_nursery() as nursery, watchdog.use(nursery):
        yield watchdog
