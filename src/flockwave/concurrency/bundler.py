from contextlib import asynccontextmanager
from trio import Lock
from trio_util import RepeatedEvent
from typing import AsyncGenerator, AsyncIterator, Generic, Iterable, TypeVar

__all__ = ("AsyncBundler",)

T = TypeVar("T")


class AsyncBundler(Generic[T]):
    """Asynchronous object that holds a bundle and supports the following
    operations:

    - Adding one or more items to the bundle

    - Waiting for the bundle to become non-empty and then removing all items
      from the bundle in one operation.

    This object is typically used in a producer-consumer setting. Producers
    add items to the bundle either one by one (with `add()`) or in batches
    (with `add_many()`). At the same time, a single consumer iterates over
    the bundle asynchronously and takes all items from it in each iteration.
    """

    _data: set[T]
    _event: RepeatedEvent
    _lock: Lock

    def __init__(self):
        """Constructor."""
        self._data = set()
        self._event = RepeatedEvent()
        self._lock = Lock()

    def add(self, item: T) -> None:
        """Adds a single item to the bundle.

        Parameters:
            item: the item to add
        """
        self._data.add(item)
        self._event.set()

    def add_many(self, items: Iterable[T]) -> None:
        """Adds multiple items to the bundle from an iterable.

        Parameters:
            items: the items to add
        """
        self._data.update(items)
        if self._data:
            self._event.set()

    def clear(self) -> None:
        """Clears all the items currently waiting in the bundle."""
        self._data.clear()

    @asynccontextmanager
    async def iter(self) -> AsyncIterator[AsyncGenerator[set[T], None]]:
        it = self.__aiter__()
        try:
            yield it
        finally:
            await it.aclose()

    async def __aiter__(self) -> AsyncGenerator[set[T], None]:
        """Asynchronously iterates over non-empty batches of items that
        were added to the set.
        """
        it = None
        try:
            if self._lock.locked():
                raise RuntimeError("AsyncBundler can only have one listener")

            async with self._lock:  # type: ignore
                it = self._event.events(repeat_last=True)
                async for _ in it:
                    result = set(self._data)
                    self._data.clear()
                    if result:
                        yield result
        finally:
            if it:
                await it.aclose()
