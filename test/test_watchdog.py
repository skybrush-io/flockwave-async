from pytest import raises
from trio import current_time, open_nursery, sleep, TooSlowError

from flockwave.concurrency import use_watchdog
from flockwave.concurrency.watchdog import Watchdog


async def test_watchdog_normal_operation(autojump_clock):
    async with use_watchdog(timeout=3) as watchdog:
        for _ in range(10):
            await sleep(0.5)
            watchdog.notify()


async def test_watchdog_expiry(autojump_clock):
    with raises(TooSlowError, match="watchdog expired"):
        async with use_watchdog(timeout=1) as watchdog:
            for i in range(10):
                await sleep(i * 0.4)
                watchdog.notify()


async def test_watchdog_never_notified(autojump_clock):
    with raises(TooSlowError, match="watchdog expired"):
        async with use_watchdog(timeout=1):
            for i in range(10):
                await sleep(i * 0.4)


async def test_sync_start(autojump_clock):
    async with open_nursery() as nursery:
        with Watchdog(timeout=1).use_soon(nursery) as watchdog:
            for _i in range(10):
                await sleep(0.5)
                watchdog.notify()
            nursery.cancel_scope.cancel()


async def test_sync_start_expiry(autojump_clock):
    with raises(TooSlowError, match="watchdog expired"):
        async with open_nursery() as nursery:
            with Watchdog(timeout=1).use_soon(nursery) as watchdog:
                for i in range(10):
                    await sleep(i * 0.4)
                    watchdog.notify()
            nursery.cancel_scope.cancel()


async def test_callback_returning_zero(autojump_clock):
    notify_called = 0
    on_expired_called = 0
    notify_call_count_when_expired = 0

    def on_expired() -> float:
        nonlocal notify_call_count_when_expired, on_expired_called
        notify_call_count_when_expired = notify_called
        on_expired_called += 1
        return 0

    async with use_watchdog(timeout=1, on_expired=on_expired) as watchdog:
        for i in range(10):
            await sleep(i * 0.4)
            watchdog.notify()
            notify_called += 1

    # watchdog.notify() must have been called three times: once at
    # t=0, once at t=0.4 and once at t=1.2. Then the watchdog stops.
    assert notify_call_count_when_expired == 3

    # on_expired() must have been called only once
    assert on_expired_called == 1


async def test_callback_returning_different_timeout(autojump_clock):
    notify_called = 0
    on_expired_called_at = []
    notify_call_count_when_expired_first = 0
    next_timeout_after_expiry = 18

    def on_expired() -> float:
        nonlocal \
            notify_call_count_when_expired_first, \
            on_expired_called_at, \
            next_timeout_after_expiry
        if notify_call_count_when_expired_first == 0:
            notify_call_count_when_expired_first = notify_called
        on_expired_called_at.append(current_time())
        next_timeout_after_expiry *= 2
        return next_timeout_after_expiry

    async with use_watchdog(timeout=10, on_expired=on_expired) as watchdog:
        for i in range(10):
            await sleep(i * 4)
            watchdog.notify()
            notify_called += 1

    # watchdog.notify() is called at these times:
    # 0, 4, 12, 24, 40, 60, 84, 112, 144, 180
    #
    # The first expiry comes at T=22, setting the deadline to 58.
    # The next expiry comes at T=58 (because notify() is called at T=40, which
    # switches the timeout period back to 1s), setting the deadline to T=50,
    # so by the time we wake up at T=58 we are already expired.
    # The next expiry comes at T=130. However, there is a notification at T=112,
    # which set the deadline to T=122, so we are already expired at T=130 when
    # we wake up. The next deadline would be at T=274.
    assert on_expired_called_at == [22, 58, 130]
    assert notify_call_count_when_expired_first == 3


async def test_callback_returning_none(autojump_clock):
    on_expired_called_at = []

    def on_expired() -> None:
        nonlocal on_expired_called_at
        on_expired_called_at.append(current_time())
        return None

    async with use_watchdog(timeout=10, on_expired=on_expired) as watchdog:
        for i in range(10):
            # Make sure we don't wait exactly until T=60 because there's also
            # an expiry there and we want to make the test deterministic
            if i == 5:
                await sleep(i * 4 - 1)
            elif i == 6:
                await sleep(i * 4 + 1)
            else:
                await sleep(i * 4)
            watchdog.notify()

    # watchdog.notify() is called at these times:
    # 0, 4, 12, 24, 40, 59, 84, 112, 144, 180

    assert on_expired_called_at == [
        22,
        34,
        50,
        69,
        79,
        94,
        104,
        122,
        132,
        142,
        154,
        164,
        174,
    ]
