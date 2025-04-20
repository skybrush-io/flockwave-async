from deprecated import deprecated

__all__ = ("aclosing",)


@deprecated(
    version="1.4.4",
    reason="Use `contextlib.aclosing` instead.",
)
class aclosing:
    """Context manager that closes an async generator when the context is
    exited. Similar to `closing()` in `contextlib`.
    """

    def __init__(self, aiter):
        self._aiter = aiter

    async def __aenter__(self):
        return self._aiter

    async def __aexit__(self, *args):
        await self._aiter.aclose()
