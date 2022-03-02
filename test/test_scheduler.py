from pytest import raises
from time import time
from trio import sleep
from typing import Optional

from flockwave.concurrency.scheduler import JobCancelled, LateSubmissionError, Scheduler


class Task:
    def __init__(self, result: int = 0, *, error: Optional[str] = None):
        self._result = result
        self._error = error
        self.called = False

    async def __call__(self) -> int:
        self.called = True
        await sleep(1)
        if self._error is not None:
            raise RuntimeError(self._error)
        else:
            return self._result


async def test_scheduler_single_job(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    task = Task(42)
    job = scheduler.schedule_after(5, task)

    assert job.outcome is None
    assert not job.running and not job.completed

    await sleep(1)

    assert job.outcome is None
    assert not job.running and not job.completed

    await sleep(4.1)

    assert job.outcome is None
    assert job.running and not job.completed

    assert 42 == await job.wait()
    assert not job.running and job.completed


async def test_scheduler_single_job_wait_twice(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    task = Task(42)
    job = scheduler.schedule_after(5, task)

    assert 42 == await job.wait()
    assert 42 == await job.wait()


async def test_scheduler_single_job_throwing_error(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    task = Task(error="foo")
    job = scheduler.schedule_after(5, task)

    with raises(RuntimeError, match="foo"):
        await job.wait()
    assert not job.running and job.completed


async def test_scheduler_does_not_crash_when_job_crashes(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    task = Task(error="foo")
    scheduler.schedule_after(5, task)
    task2 = Task(42)
    job = scheduler.schedule_after(7, task2)

    await sleep(9)
    assert not job.running and job.completed
    assert 42 == await job.wait()


async def test_scheduler_multiple_jobs(nursery, autojump_clock):
    scheduler = Scheduler()
    job = scheduler.schedule_after(3, Task(1))
    job2 = scheduler.schedule_at(time() + 5, Task(error="bar"))
    await nursery.start(scheduler.run)

    job3 = scheduler.schedule_after(5.5, Task(3))

    jobs = [job, job2, job3]
    assert not any(job.running or job.completed for job in jobs)

    await sleep(2)
    assert not any(job.running or job.completed for job in jobs)

    await sleep(1.1)
    assert job.running and not job.completed
    assert not job2.running and not job2.completed
    assert not job3.running and not job3.completed

    await sleep(1)
    assert not job.running and job.completed
    assert 1 == await job.wait()
    assert not job2.running and not job2.completed
    assert not job3.running and not job3.completed

    await sleep(1)
    assert not job.running and job.completed
    assert job2.running and not job2.completed
    assert not job3.running and not job3.completed

    await sleep(0.5)
    assert not job.running and job.completed
    assert job2.running and not job2.completed
    assert job3.running and not job3.completed

    with raises(RuntimeError, match="bar"):
        await job2.wait()
    assert not job.running and job.completed
    assert not job2.running and job2.completed
    assert job3.running and not job3.completed

    await sleep(0.51)
    assert all(not job.running and job.completed for job in jobs)
    assert 3 == await job3.wait()


async def test_job_cancellation(nursery, autojump_clock):
    scheduler = Scheduler()
    job = scheduler.schedule_after(3, Task(1))

    await nursery.start(scheduler.run)

    await sleep(1)
    scheduler.cancel(job)
    assert not job.running and job.completed

    with raises(JobCancelled):
        await job.wait()


async def test_job_cancellation_when_running(nursery, autojump_clock):
    scheduler = Scheduler()
    job = scheduler.schedule_after(3, Task(1))

    await nursery.start(scheduler.run)

    await sleep(3.5)
    scheduler.cancel(job)
    assert not job.running and job.completed

    with raises(JobCancelled):
        await job.wait()


async def test_job_rescheduling(nursery, autojump_clock):
    scheduler = Scheduler()
    job = scheduler.schedule_after(3, Task(1))
    job2 = scheduler.schedule_after(5, Task(2))
    job3 = scheduler.schedule_after(7, Task(3))

    await nursery.start(scheduler.run)

    await sleep(0.5)
    scheduler.reschedule_after(0.5, job2)

    assert not job2.running and not job2.completed
    await sleep(0.6)
    assert job2.running and not job2.completed
    await sleep(1)
    assert not job2.running and job2.completed
    assert 2 == await job2.wait()

    scheduler.reschedule_to(time() + 7.9, job)
    assert 3 == await job3.wait()
    assert not job.running and not job.completed
    await sleep(2.1)
    assert job.running and not job.completed
    await sleep(1)
    assert not job.running and job.completed
    assert 1 == await job.wait()

    job4 = scheduler.schedule_after(1, Task(4))
    await sleep(1.5)
    with raises(RuntimeError, match="started already"):
        scheduler.reschedule_after(1, job4)

    job5 = scheduler.schedule_at(time() + 0.1, Task(4))
    await sleep(0.6)
    with raises(RuntimeError, match="started already"):
        scheduler.reschedule_to(time() + 1, job5)


async def test_job_running_twice(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    job = scheduler.schedule_after(3, Task(1))
    assert 1 == await job.wait()
    with raises(RuntimeError, match="already executed"):
        await job._run()

    job = scheduler.schedule_after(3, Task(1))
    await sleep(3.5)
    with raises(RuntimeError, match="running"):
        await job._run()


async def test_job_late_cancellation(nursery, autojump_clock):
    scheduler = Scheduler()
    await nursery.start(scheduler.run)

    job = scheduler.schedule_after(3, Task(1))
    assert 1 == await job.wait()

    scheduler.cancel(job)
    assert 1 == await job.wait()


async def test_job_late_submission():
    scheduler = Scheduler()
    assert scheduler.allow_late_submissions

    scheduler = Scheduler(allow_late_submissions=False)
    assert not scheduler.allow_late_submissions

    scheduler = Scheduler(allow_late_submissions=True)
    assert scheduler.allow_late_submissions

    # This should be OK
    scheduler.schedule_after(-3, Task(1))

    # This is not OK
    scheduler.allow_late_submissions = False
    with raises(LateSubmissionError):
        scheduler.schedule_after(-3, Task(1))


async def test_job_rescheduling_to_past(nursery, autojump_clock):
    scheduler = Scheduler(allow_late_submissions=False)
    job = scheduler.schedule_after(3, Task(1))

    await nursery.start(scheduler.run)

    with raises(LateSubmissionError):
        scheduler.reschedule_after(-3, job)

    # Failed rescheduling should keep the start time intact
    assert not job.running and not job.completed
    await sleep(3.1)
    assert job.running and not job.completed
    assert 1 == await job.wait()
