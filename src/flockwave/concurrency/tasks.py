from functools import partial, wraps
from trio import CancelScope, Event, Nursery
from typing import TypeVar

__all__ = ("cancellable", "CancellableTaskGroup", "AwaitableCancelScope")


def cancellable(func):
    """Decorator that extends an async function with an extra `cancel_scope`
    keyword argument and makes the function enter the cancel scope.
    """

    @wraps(func)
    async def decorated(*args, cancel_scope, **kwds):
        with cancel_scope:
            return await func(*args, **kwds)

    decorated._cancellable = True  # type: ignore

    return decorated


class CancellableTaskGroup:
    """Object representing a group of tasks running in an associated nursery
    that can be cancelled with a single method call.
    """

    def __init__(self, nursery: Nursery):
        """Constructor.

        Parameters:
            nursery: the nursery that the tasks of the task group will be
                executed in.
        """
        self._nursery = nursery
        self._cancel_scopes = []

    def cancel_all(self) -> None:
        """Cancels all tasks running in the task group."""
        for cancel_scope in self._cancel_scopes:
            cancel_scope.cancel()
        del self._cancel_scopes[:]

    def start_soon(self, func, *args):
        """Starts a new task in the task group."""
        cancel_scope = CancelScope()
        self._cancel_scopes.append(cancel_scope)
        self._nursery.start_soon(partial(cancellable(func), cancel_scope=cancel_scope))


C = TypeVar("C", bound="AwaitableCancelScope")


class AwaitableCancelScope:
    """Wrapper for a Trio cancel scope that allows waiting until the cancellation
    has been processed.

    This object wraps a cancel scope and an event. Unlike in a Trio cancel
    scope, `cancel()` is an async operation that calls `cancel()` in the wrapped
    cancel scope and then waits for the event. The task that the cancel scope
    cancels is expected to trigger the event when it is about to terminate.
    """

    _wrapped_cancel_scope: CancelScope
    """The native Trio cancel scope wrapped by this instance."""

    _event: Event
    """The event that must be set by the associated task when the cancellation
    was processed.
    """

    _entered: bool
    """Whether the wrapped native Trio cancel scope was entered."""

    def __init__(self):
        self._entered = False
        self._wrapped_cancel_scope = CancelScope()
        self._event = Event()

    async def cancel(self) -> None:
        """Cancels the cancel scope and waits for the cancellation to be
        processed by the associated task.
        """
        self.cancel_nowait()
        if self._entered:
            await self._event.wait()

    def cancel_nowait(self) -> None:
        """Cancels the cancel scope and returns immediately, without waiting
        for the cancellation to be processed by the associated task.
        """
        self._wrapped_cancel_scope.cancel()

    def notify_processed(self) -> None:
        """Notifies the cancel scope that the cancellation has been processed.
        This is called automatically when the cancel scope is exited, but you
        may also call it manually if needed.
        """
        self._event.set()

    def __enter__(self: C) -> C:
        if self._entered:
            raise RuntimeError("AwaitableCancelScope may only be entered once")
        self._wrapped_cancel_scope.__enter__()
        self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, tb) -> bool:
        try:
            return self._wrapped_cancel_scope.__exit__(exc_type, exc_value, tb)
        finally:
            self.notify_processed()
