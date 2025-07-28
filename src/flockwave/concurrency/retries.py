"""Classes for retry policies and a helper function to execute a fallible
operation with a retry policy.
"""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional, TypeVar

from anyio import current_time, fail_after

__all__ = ("RetryPolicy", "FixedRetryPolicy", "run_with_retries")


class RetryPolicy(ABC):
    """A policy for retrying an operation that may possibly time out.

    This class encapsulates the logic for determining how many retries to perform,
    the timeout for each retry, and how to handle failures.

    You can re-use the same policy for multiple _related_ operations to allow
    for adaptive timeouts based on the success or failure of previous attempts.

    Do not re-use the same policy for unrelated operations; create a factory
    function that returns a new instance of the policy for each unrelated
    operation.
    """

    @abstractmethod
    def notify_start(self) -> float:
        """Notifies the policy that a new operation is starting.

        Returns:
            the initial timeout of the first attempt of the operation.
        """
        ...

    @abstractmethod
    def notify_finished(self, retries_needed: int, rtt: Optional[float]) -> None:
        """Handles the case when the operation finished (either successfully or
        by throwing an exception).

        Args:
            retries_needed: The number of retries that were needed to succeed.
                Zero means that the operation finished on the first try.
            rtt: The round-trip time of the operation, if known. The round-trip
                time is the time it took to complete the operation, including any
                retries. May be used to adjust future timeouts or retry logic.
        """
        ...

    @abstractmethod
    def notify_timeout(self) -> Optional[float]:
        """Handles a timeout in the operation.

        Returns:
            The suggested timeout for the next retry, or None if no more retries
            should be attempted.
        """
        ...


class FixedRetryPolicy(RetryPolicy):
    """A retry policy that retries the operation a fixed number of times, with a
    fixed timeout between attempts.
    """

    max_retries: int
    """The number of retries to perform."""

    timeout: float
    """The timeout for each retry in seconds."""

    _remaining: int
    """The number of retries remaining."""

    def __init__(self, *, max_retries: int, timeout: float):
        self.max_retries = max_retries
        self.timeout = timeout
        self.notify_start()

    def notify_start(self) -> float:
        self._remaining = self.max_retries
        return self.timeout

    def notify_finished(self, retries_needed: int, rtt: Optional[float]) -> None:
        pass

    def notify_timeout(self):
        if self._remaining > 0:
            self._remaining -= 1
            return self.timeout
        else:
            return None


class ExponentialBackoffPolicy(RetryPolicy):
    """A retry policy that retries the operation with an exponential backoff."""

    max_retries: Optional[int]
    """The number of retries to perform; ``None`` means unlimited retries."""

    base_timeout: float
    """The base timeout for the first attempt in seconds."""

    scale_factor: float = 2.0
    """The factor by which the timeout is multiplied after each retry."""

    max_timeout: Optional[float] = None
    """The maximum timeout for the retries, if any."""

    _remaining: float
    """The number of retries remaining."""

    _next_timeout: float
    """The timeout for the next retry in seconds."""

    def __init__(
        self,
        *,
        max_retries: int,
        base_timeout: float,
        scale_factor: float = 2.0,
        max_timeout: Optional[float] = None,
    ):
        self.max_retries = max_retries
        self.scale_factor = scale_factor
        self.max_timeout = max_timeout
        self._set_base_timeout(base_timeout)
        self.notify_start()

    def _set_base_timeout(self, value: float) -> None:
        if self.max_timeout is not None and value > self.max_timeout:
            self.base_timeout = self.max_timeout
        else:
            self.base_timeout = value

    def notify_start(self) -> float:
        self._remaining = (
            self.max_retries if self.max_retries is not None else float("inf")
        )
        self._next_timeout = self.base_timeout
        return self._next_timeout

    def notify_finished(self, retries_needed: int, rtt: Optional[float]) -> None:
        pass

    def notify_timeout(self) -> Optional[float]:
        if self._remaining > 0:
            self._next_timeout *= self.scale_factor
            if self.max_timeout is not None:
                self._next_timeout = min(self._next_timeout, self.max_timeout)

            self._remaining -= 1
            return self._next_timeout
        else:
            return None


class AdaptiveExponentialBackoffPolicy(ExponentialBackoffPolicy):
    """An adaptive exponential backoff policy that adjusts the initial timeout
    based on the round-trip time of the operation.

    This policy can be used to implement a policy that is similar to how TCP
    connections handle retransmissions (see RFC 6298). The initial timeout is
    set based on a smoothed round-trip time estimate, which is updated with each
    successful operation _that required no retries_.

    The initial timeout is set to be SRTT + max(4 * RTTVAR, G) where SRTT is
    the smoothed round-trip estimate, RTTVAR is the RTT variance and G is the
    clock granularity. SRTT is initialized with RTT after the first successful
    operation, while RTTVAR is initialized with RTT/2. Further updates are
    performed according to the following formula:

        RTTVAR = (1 - beta) * RTTVAR + beta * abs(SRTT - RTT)
        SRTT = (1 - alpha) * SRTT + alpha * RTT

    where alpha and beta are constants that control the smoothing. The default
    values are alpha = 1/8 and beta = 1/4, which are the same as the
    ones used in TCP.
    """

    alpha: float = 1 / 8.0
    """The smoothing factor for the SRTT estimate."""

    beta: float = 1 / 4.0
    """The smoothing factor for the RTTVAR estimate."""

    min_timeout: float
    """The minimum timeout, set as half of the base timeout by default (but can
    be overridden by the user).
    """

    _srtt_initialized: bool = False
    _srtt: float = 0.0
    _rttvar: float = 0.0

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.min_timeout = self.base_timeout / 2

    def notify_finished(self, retries_needed: int, rtt: Optional[float]) -> None:
        if rtt is not None and retries_needed == 0:
            self._update_state(rtt)

        super().notify_finished(retries_needed, rtt)

    def _update_state(self, rtt: float) -> None:
        """Updates the state variables of the policy based on the round-trip
        time of the last operation.
        """
        if not self._srtt_initialized:
            self._srtt = rtt
            self._rttvar = rtt / 2.0
            self._srtt_initialized = True
        else:
            self._rttvar = (1 - self.beta) * self._rttvar + self.beta * abs(
                self._srtt - rtt
            )
            self._srtt = (1 - self.alpha) * self._srtt + self.alpha * rtt

        granularity = 0.001
        self._set_base_timeout(
            max(self._srtt + max(4 * self._rttvar, granularity), self.min_timeout)
        )


T = TypeVar("T")


async def run_with_retries(func: Callable[[], Awaitable[T]], policy: RetryPolicy) -> T:
    """Runs an async function with retries according to the given policy.

    Args:
        func: The async function to run.
        policy: The retry policy to use.

    Returns:
        The result of the function if it succeeds.

    Raises:
        TimeoutError: If the function fails after all retries.
    """
    timeout = policy.notify_start()
    retries = 0

    start = current_time()
    while True:
        try:
            with fail_after(timeout):
                result = await func()

        except TimeoutError:
            retries += 1
            timeout = policy.notify_timeout()
            if timeout is None:
                raise

        else:
            rtt = current_time() - start
            policy.notify_finished(retries, rtt)
            return result
