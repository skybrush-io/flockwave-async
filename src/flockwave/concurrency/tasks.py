from functools import partial, wraps
from trio import CancelScope, Nursery

__all__ = ("cancellable", "CancellableTaskGroup")


def cancellable(func):
    """Decorator that extends an async function with an extra `cancel_scope`
    keyword argument and makes the function enter the cancel scope.
    """

    @wraps(func)
    async def decorated(*args, cancel_scope, **kwds):
        with cancel_scope:
            return await func(*args, **kwds)

    decorated._cancellable = True

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
