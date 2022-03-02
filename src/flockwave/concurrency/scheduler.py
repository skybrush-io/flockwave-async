"""Simple scheduler for starting asynchronous tasks in the future."""

from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from heapq import heappop, heappush
from math import inf
from outcome import acapture, Outcome, Error
from time import time as posix_time
from typing import (
    cast,
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Union,
    TypeVar,
)

from trio import (
    CancelScope,
    Event,
    Nursery,
    current_time as trio_time,
    open_nursery,
    sleep_forever,
    TASK_STATUS_IGNORED,
)

__all__ = ("Job", "JobCancelled", "LateSubmissionError", "Scheduler")

T = TypeVar("T")


class JobCancelled(RuntimeError):
    """Error thrown when trying to retrieve the result of a job that has been
    cancelled.
    """

    pass


class LateSubmissionError(RuntimeError):
    """Error thrown when trying to schedule a job to a timestamp that is in the
    past and the scheduler is set up to disallow such submissions.
    """

    pass


@dataclass
class Job(Generic[T]):
    """A single job in the scheduler."""

    func: Optional[Callable[[], Awaitable[T]]]
    """The sync or async function of the job; ``None`` if the job was
    invalidated due to a change in its scheduled start time.
    """

    outcome: Optional[Outcome] = None
    """The result of the job"""

    _cancel_scope: CancelScope = field(default_factory=CancelScope)
    """The cancel scope of the job that can be used to cancel it when it is
    already running.
    """

    _running: bool = False
    """Whether the job is running."""

    _completed: Event = field(default_factory=Event)
    """Event that is triggered when the job has finished."""

    @property
    def completed(self) -> bool:
        """Returns whether the job has finished."""
        return self._completed.is_set()

    @property
    def running(self) -> bool:
        """Returns whether the job is running."""
        return self._running

    def _cancel(self) -> None:
        """Cancels the job if it has not completed yet. No-op if the job has
        already finished.
        """
        if self.outcome is not None:
            # Job was already executed, do nothing
            return

        if self._running:
            self._cancel_scope.cancel()

        self._record_cancellation()

    async def _run(self) -> None:
        """Executes the job and stores its result when done."""
        if self.outcome is not None:
            raise RuntimeError("The job was already executed")
        elif self._running:
            raise RuntimeError("The job is already running")

        self._running = True
        with self._cancel_scope:
            self._set_outcome(await acapture(self.func))

    def _record_cancellation(self) -> None:
        self._set_outcome(Error(JobCancelled()))  # type: ignore

    def _set_outcome(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self._completed.set()
        self._running = False

    async def wait(self) -> T:
        """Waits for the result of the job. Returns the result of the job
        when completed successfully, or raises an exception if the job
        terminated with an exception.
        """
        await self._completed.wait()
        assert self.outcome is not None
        object.__setattr__(
            self.outcome, "_unwrapped", False
        )  # to allow calling wait() twice
        return cast(T, self.outcome.unwrap())


@dataclass(order=True)
class SchedulerItem(Generic[T]):
    """A single job in the scheduler."""

    scheduled_time: float
    """Time when the job is supposed to start."""

    job: Optional[Job[T]] = field(compare=False)
    """The job itself; ``None`` if the item was invalidated."""

    def _invalidate(self) -> None:
        """Invalidates the item when the job is re-scheduled with a new
        start time.
        """
        self.job = None


class Scheduler(Generic[T]):
    """Simple scheduler for starting asynchronous tasks in the future."""

    _cancel_scope: CancelScope
    """The cancel scope that stores the next wakeup time of the scheduler."""

    _heap: List[SchedulerItem[T]]
    """The list of jobs in the scheduler, along with their timestamps."""

    _jobs_to_items: Dict[int, SchedulerItem[T]]
    """Dictionary mapping IDs jobs to their currently active scheduler items."""

    allow_late_submissions: bool = True
    """Whether the scheduler allows late submissions (i.e. jobs that are
    scheduled to a time that is earlier than the current time when they are
    submitted). Setting this property to ``False`` will make the scheduler throw
    a LateSubmissionError_ when someone tries to (re)schedule a job to a
    timestamp that is earlier than the current time.
    """

    def __init__(self, allow_late_submissions: bool = True):
        """Constructor."""
        self.allow_late_submissions = bool(allow_late_submissions)
        self._cancel_scope = CancelScope()
        self._heap = []
        self._jobs_to_items = {}

    def cancel(self, job: Job[T]) -> None:
        """Cancels an already scheduled job."""
        item = self._jobs_to_items.pop(id(job), None)
        if item is not None:
            item._invalidate()
        job._cancel()

    def schedule_at(
        self,
        scheduled_time: Union[float, datetime],
        func: Callable[..., Awaitable[T]],
        *args,
    ) -> Job[T]:
        """Schedules the given function to be called at the given time.

        Extra positional arguments are forwarded to the function.

        Note that this function will _not_ work correctly if the system clock
        is adjusted after the job has been scheduled; the delay to the job start
        will still be based on the old timestamp.

        Parameters:
            scheduled_time: the time when the function must be called, either
                as a POSIX timestamp or as a datetime object
            func: the function to call

        Returns:
            the scheduled job
        """
        timestamp = self._local_to_trio_time(scheduled_time)
        job = Job(cast(Any, partial(func, *args) if args else func))
        return self._schedule(timestamp, job)

    def schedule_after(
        self, delay: float, func: Callable[..., Awaitable[T]], *args
    ) -> Job[T]:
        """Schedules the given function to be called after a given number of
        seconds.

        Extra positional arguments are forwarded to the function.

        Parameters:
            delay: the number of seconds that must pass before the function is
                called
            func: the function to call

        Returns:
            the scheduled job
        """
        self._validate_delay(delay)
        job = Job(cast(Any, partial(func, *args) if args else func))
        return self._schedule(trio_time() + delay, job)

    def reschedule_to(
        self, scheduled_time: Union[float, datetime], job: Job[T]
    ) -> None:
        """Reschedules a job so it is executed at a later time.

        Parameters:
            scheduled_time: the new scheduled start time of the job
            job: the job to reschedule

        Raises:
            RuntimeError: if the job is already running
        """
        item = self._pop_scheduler_item_for_job(job)
        self._reschedule(self._local_to_trio_time(scheduled_time), item)

    def reschedule_after(self, delay: float, job: Job[T]) -> None:
        """Reschedules a job so it is executed after a given number of
        seconds.

        Parameters:
            delay: the number of seconds that must pass before the function is
                called
            job: the job to reschedule

        Raises:
            RuntimeError: if the job is already running
        """
        self._validate_delay(delay)
        item = self._pop_scheduler_item_for_job(job)
        self._reschedule(trio_time() + delay, item)

    async def run(self, task_status=TASK_STATUS_IGNORED) -> None:
        """Runs the scheduler."""
        async with open_nursery() as nursery:
            task_status.started()
            while True:
                self._start_expired_jobs_in(nursery)

                next_deadline = self._heap[0].scheduled_time if self._heap else inf
                self._cancel_scope = CancelScope(deadline=next_deadline)  # type: ignore
                with self._cancel_scope:
                    await sleep_forever()

    def _local_to_trio_time(self, timestamp: Union[float, datetime]) -> float:
        """Converts a "local" (POSIX) timestamp to a Trio timestamp.

        Raises:
            LateSubmissionError: when the timestamp is in the past and the
                ``allow_late_submissions`` property is set to ``False``.
        """
        # TODO(ntamas): this solution ignores the case when the system clock is
        # adjusted while the job is already scheduled.
        delay = (
            float(timestamp)
            if isinstance(timestamp, (float, int))
            else timestamp.timestamp()
        ) - posix_time()
        self._validate_delay(delay)
        return trio_time() + delay

    def _pop_scheduler_item_for_job(self, job: Job[T]) -> SchedulerItem[T]:
        """Returns the scheduler item corresponding to the given job and removes
        it from the internal jobs-to-items hash.

        Raises:
            RuntimeError: if the job execution has started already and the item
                was removed from the scheduler.
        """
        item = self._jobs_to_items.pop(id(job), None)
        if item is None:
            raise RuntimeError("Job execution has started already")
        return item

    def _schedule(self, timestamp: float, job: Job[T]) -> Job[T]:
        """Schedules a job to be called at the given Trio timestamp (which
        is not based on POSIX time). It is assumed that the job is not
        scheduled yet.
        """
        item = SchedulerItem(timestamp, job)

        heappush(self._heap, item)
        self._jobs_to_items[id(job)] = item

        if timestamp < self._cancel_scope.deadline:
            self._cancel_scope.deadline = timestamp

        return job

    def _reschedule(self, timestamp: float, item: SchedulerItem[T]) -> None:
        job = item.job
        assert job is not None

        item._invalidate()
        self._schedule(timestamp, job)

    def _start_expired_jobs_in(self, nursery: Nursery) -> None:
        now = trio_time()
        while self._heap and self._heap[0].scheduled_time <= now:
            item = heappop(self._heap)
            job = item.job
            if job is not None:
                del self._jobs_to_items[id(job)]
                nursery.start_soon(job._run)

    def _validate_delay(self, delay: float) -> None:
        if delay < 0 and not self.allow_late_submissions:
            delay = round(float(delay), 2)
            raise LateSubmissionError(
                f"Tried to schedule job to {-delay} seconds in the past"
            )
