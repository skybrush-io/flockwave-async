from pytest import raises
from trio import move_on_after, sleep

from flockwave.concurrency import AsyncBundler


async def test_yields_nothing_when_empty(autojump_clock):
    with move_on_after(10):
        async for bundle in AsyncBundler():
            assert False, "bundler should not yield any bundles"


async def test_yields_all_items_after_add(autojump_clock):
    bundler = AsyncBundler()
    with move_on_after(10):
        bundler.add(2)
        bundler.add(3)
        bundler.add(5)
        async for bundle in bundler:
            assert bundle == set([2, 3, 5])


async def test_yields_all_items_after_add_many(autojump_clock):
    bundler = AsyncBundler()
    with move_on_after(10):
        bundler.add_many([2, 3, 5, 7])
        bundler.add_many((11, 13))
        async for bundle in bundler:
            assert bundle == set([2, 3, 5, 7, 11, 13])


async def test_clears_items_after_yielding(autojump_clock):
    bundler = AsyncBundler()
    with move_on_after(10):
        bundler.add_many([2, 3, 5, 7])
        async with bundler.iter() as bundle_iter:
            async for bundle in bundle_iter:
                assert bundle == set([2, 3, 5, 7])
                break

        bundler.add_many((11, 13))

        was_in_loop = False
        async for bundle in bundler:
            assert bundle == set([11, 13])
            was_in_loop = True
        assert was_in_loop


async def test_clears_items_before_yielding(autojump_clock):
    bundler = AsyncBundler()
    with move_on_after(10):
        bundler.add_many([2, 3, 5, 7])
        bundler.clear()
        async with bundler.iter() as bundle_iter:
            async for bundle in bundle_iter:
                assert bundle == set()
                break

        bundler.add_many([2, 3, 5, 7])
        bundler.clear()
        bundler.add_many([11, 13])

        was_in_loop = False
        async for bundle in bundler:
            assert bundle == set([11, 13])
            was_in_loop = True
        assert was_in_loop


async def test_filters_duplicates(autojump_clock):
    bundler = AsyncBundler()
    with move_on_after(10):
        bundler.add_many([2, 3, 3, 5, 5, 5, 7])
        async with bundler.iter() as bundle_iter:
            async for bundle in bundle_iter:
                assert bundle == set([2, 3, 5, 7])
                break
        bundler.add_many((2, 2, 3, 11))

        was_in_loop = False
        async for bundle in bundler:
            assert bundle == set([2, 3, 11])
            was_in_loop = True
        assert was_in_loop


async def test_separated_producer_consumer(autojump_clock, nursery):
    bundler = AsyncBundler()

    async def producer(task_status):
        task_status.started()
        items = list(range(10))
        for item in items:
            bundler.add(item)
            await sleep(0.21)

    async def consumer():
        bundles = []
        with move_on_after(10):
            async for bundle in bundler:
                bundles.append(bundle)
                await sleep(0.5)
        return bundles

    await nursery.start(producer)
    bundles = await consumer()

    assert len(bundles) == 5
    assert bundles[0] == {0}
    assert bundles[1] == {1, 2}
    assert bundles[2] == {3, 4}
    assert bundles[3] == {5, 6, 7}
    assert bundles[4] == {8, 9}


async def test_multiple_consumers(autojump_clock, nursery):
    bundler = AsyncBundler()

    async def consumer():
        return [bundle async for bundle in bundler]

    nursery.start_soon(consumer)
    await sleep(0.02)

    with raises(RuntimeError) as ex:
        await consumer()

    assert "can only have one listener" in str(ex.value)
