from inspect import signature
from trio import sleep

from flockwave.concurrency import cancellable, CancellableTaskGroup


async def test_cancellable(autojump_clock):
    test_var = 42

    async def func(foo, bar: int = 42, *, baz):
        nonlocal test_var
        await sleep(5)
        test_var = 84

    cancellable_func = cancellable(func)

    sig = signature(cancellable_func, follow_wrapped=False)
    assert str(sig) == "(*args, cancel_scope, **kwds)"

    sig = signature(func, follow_wrapped=False)
    assert signature(cancellable_func, follow_wrapped=True) == signature(func)


class TestCancellableTaskGroup:
    async def test_cancel_empty(self, nursery):
        tg = CancellableTaskGroup(nursery)
        tg.cancel_all()
        assert True

    async def test_cancel_multiple(self, nursery):
        tg = CancellableTaskGroup(nursery)
        tg.cancel_all()
        tg.cancel_all()
        tg.cancel_all()
        assert True

    async def test_start_and_cancel(self, autojump_clock, nursery):
        ended1, ended2 = False, False

        async def task1():
            nonlocal ended1
            await sleep(5)
            ended1 = True

        async def task2():
            nonlocal ended2
            await sleep(3)
            ended2 = True

        await task1()
        assert ended1

        await task2()
        assert ended2

        ended1, ended2 = False, False

        tg = CancellableTaskGroup(nursery)
        tg.start_soon(task1)
        tg.start_soon(task2)
        await sleep(2)
        tg.cancel_all()
        assert not ended1 and not ended2

        ended1, ended2 = False, False

        tg = CancellableTaskGroup(nursery)
        tg.start_soon(task1)
        tg.start_soon(task2)
        await sleep(4)
        assert ended2 and not ended1
        tg.cancel_all()

        await sleep(5)
        assert ended2 and not ended1
