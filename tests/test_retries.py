from anyio import sleep
from pytest import raises
from flockwave.concurrency import (
    AdaptiveExponentialBackoffPolicy,
    ExponentialBackoffPolicy,
    FixedRetryPolicy,
    run_with_retries,
)


class TestFixedRetryPolicy:
    def test_initialization(self):
        policy = FixedRetryPolicy(max_retries=3, timeout=2.5)
        assert policy.max_retries == 3
        assert policy.timeout == 2.5

    def test_notify_start(self):
        policy = FixedRetryPolicy(max_retries=2, timeout=1.0)
        assert policy.notify_start() == 1.0

    def test_notify_failure_returns_same_timeout_until_exhausted(self):
        policy = FixedRetryPolicy(max_retries=5, timeout=0.5)
        assert policy.notify_start() == 0.5
        for _ in range(5):
            assert policy.notify_timeout() == 0.5
        assert policy.notify_timeout() is None
        assert policy.notify_timeout() is None

    def test_notify_success_does_not_raise(self):
        policy = FixedRetryPolicy(max_retries=1, timeout=1.0)
        policy.notify_start()
        # Should not raise any exception
        policy.notify_finished(retries_needed=0, rtt=None)
        policy.notify_finished(retries_needed=2, rtt=0.3)


class TestExponentialBackoffPolicy:
    def test_initialization(self):
        policy = ExponentialBackoffPolicy(max_retries=3, base_timeout=1.0)
        assert policy.max_retries == 3
        assert policy.base_timeout == 1.0
        assert policy.scale_factor == 2.0
        assert policy.max_timeout is None

    def test_notify_start(self):
        policy = ExponentialBackoffPolicy(max_retries=2, base_timeout=1.0)
        assert policy.notify_start() == 1.0

    def test_notify_timeout_exponential_backoff(self):
        policy = ExponentialBackoffPolicy(max_retries=3, base_timeout=1.0)
        assert policy.notify_start() == 1.0
        assert policy.notify_timeout() == 2.0
        assert policy.notify_timeout() == 4.0
        assert policy.notify_timeout() == 8.0
        assert policy.notify_timeout() is None
        policy.notify_finished(4, 100)

    def test_notify_timeout_exponential_backoff_with_max(self):
        policy = ExponentialBackoffPolicy(
            max_retries=3, base_timeout=1.0, max_timeout=7.0
        )
        assert policy.notify_start() == 1.0
        assert policy.notify_timeout() == 2.0
        assert policy.notify_timeout() == 4.0
        assert policy.notify_timeout() == 7.0
        assert policy.notify_timeout() is None

    def test_notify_timeout_exponential_backoff_with_max_and_scale_factor(self):
        policy = ExponentialBackoffPolicy(
            max_retries=3, base_timeout=1.0, max_timeout=17.0, scale_factor=3.0
        )
        assert policy.notify_start() == 1.0
        assert policy.notify_timeout() == 3.0
        assert policy.notify_timeout() == 9.0
        assert policy.notify_timeout() == 17.0
        assert policy.notify_timeout() is None


class TestAdaptiveExponentialBackoffPolicy:
    """Test the AdaptiveExponentialBackoffPolicy with various scenarios."""

    async def test_initialization(self):
        policy = AdaptiveExponentialBackoffPolicy(max_retries=3, base_timeout=1.0)
        assert policy.max_retries == 3
        assert policy.base_timeout == 1.0

    async def test_notify_start(self):
        policy = AdaptiveExponentialBackoffPolicy(max_retries=2, base_timeout=1.0)
        assert policy.notify_start() == 1.0

    async def test_successful_operation_updates_base_timeout(self):
        policy = AdaptiveExponentialBackoffPolicy(max_retries=None, base_timeout=1.0)
        assert policy.notify_start() == 1.0
        policy.notify_finished(retries_needed=0, rtt=0.5)

        # SRTT = RTT = 0.5
        # RTTVAR = RTT / 2 = 0.25
        # RTO = SRTT + max(4 * RTTVAR, G) = 0.5 + 1.0 = 1.5
        assert policy.notify_start() == 1.5
        policy.notify_finished(retries_needed=0, rtt=0.5)

        # RTTVAR = 0.75 * 0.25 + 0.25 * abs(0.5 - 0.5) = 0.1875
        # SRTT = 0.875 * 0.5 + 0.125 * 0.5 = 0.5
        # RTO = SRTT + max(4 * RTTVAR, G) = 0.5 + 0.75 = 1.25
        assert policy.notify_start() == 1.25
        policy.notify_finished(retries_needed=0, rtt=2.0)

        # RTTVAR = 0.75 * 0.1875 + 0.25 * abs(0.5 - 2.0) = 0.515625
        # SRTT = 0.875 * 0.5 + 0.125 * 2.0 = 0.6875
        # RTO = SRTT + max(4 * RTTVAR, G) = 0.6875 + 4 * 0.515625 = 2.75
        assert policy.notify_start() == 2.75

    async def test_successful_operation_with_retries_does_not_update_base_timeout(self):
        policy = AdaptiveExponentialBackoffPolicy(max_retries=3, base_timeout=1.0)
        assert policy.notify_start() == 1.0

        # Simulate a successful operation that required retries
        policy.notify_finished(retries_needed=2, rtt=0.5)
        assert policy.base_timeout == 1.0


async def fallible_function():
    """A function that simulates a failure unconditinally."""
    await sleep(1)
    raise TimeoutError()


async def successful_function():
    """A function that simulates a successful operation."""
    return "Success"


class FunctionWithFixedFailureCount:
    """A function that fails a fixed number of times before succeeding."""

    def __init__(self, fail_count: int):
        self.fail_count = fail_count
        self.current_fail = 0

    async def __call__(self):
        if self.current_fail < self.fail_count:
            self.current_fail += 1
            raise TimeoutError()
        return "Success"


class TestRunWithRetries:
    """Test the run_with_retries function with a FixedRetryPolicy."""

    async def test_successful_run(self, autojump_clock):
        """Test that run_with_retries succeeds when the function does not raise."""

        policy = FixedRetryPolicy(max_retries=3, timeout=0.5)
        result = await run_with_retries(successful_function, policy)
        assert result == "Success"
        assert policy._remaining == 3

    async def test_fixed_failures(self, autojump_clock):
        """Test that run_with_retries retries a fixed number of times before succeeding."""
        fail_count = 2
        policy = FixedRetryPolicy(max_retries=fail_count * 2, timeout=0.5)

        function = FunctionWithFixedFailureCount(fail_count)
        result = await run_with_retries(function, policy)
        assert result == "Success"
        assert policy._remaining == fail_count

        # Try again to ensure that the failure policy is reset between runs
        function = FunctionWithFixedFailureCount(fail_count)
        result = await run_with_retries(function, policy)
        assert result == "Success"
        assert policy._remaining == fail_count

    async def test_failure_with_retries(self, autojump_clock):
        """Test that run_with_retries retries on failure."""
        policy = FixedRetryPolicy(max_retries=2, timeout=0.5)
        with raises(TimeoutError):
            await run_with_retries(fallible_function, policy)
        assert policy._remaining == 0
