# Copyright 2009 Brian Quinlan. All Rights Reserved. See LICENSE file.

__author__ = 'Brian Quinlan (brian@sweetapp.com)'

import functools
import logging
import threading
import time

FIRST_COMPLETED = 'FIRST_COMPLETED'
FIRST_EXCEPTION = 'FIRST_EXCEPTION'
ALL_COMPLETED = 'ALL_COMPLETED'
RETURN_IMMEDIATELY = 'RETURN_IMMEDIATELY'

# Possible future states (for internal use by the futures package).
PENDING = 'PENDING'
RUNNING = 'RUNNING'
# The future was cancelled by the user...
CANCELLED = 'CANCELLED'                            
# ...and ThreadEventSink.add_cancelled() was called by a worker.
CANCELLED_AND_NOTIFIED = 'CANCELLED_AND_NOTIFIED'
FINISHED = 'FINISHED'

_FUTURE_STATES = [
    PENDING,
    RUNNING,
    CANCELLED,
    CANCELLED_AND_NOTIFIED,
    FINISHED
]

_STATE_TO_DESCRIPTION_MAP = {
    PENDING: "pending",
    RUNNING: "running",
    CANCELLED: "cancelled",
    CANCELLED_AND_NOTIFIED: "cancelled",
    FINISHED: "finished"
}

# Logger for internal use by the futures package.
LOGGER = logging.getLogger("futures")
_handler = logging.StreamHandler()
LOGGER.addHandler(_handler)
del _handler

class Error(Exception):
    pass

class CancelledError(Error):
    pass

class TimeoutError(Error):
    pass

class _Waiter(object):
    """Provides the event that FutureList.wait(...) blocks on.

    """
    def __init__(self):
        self.event = threading.Event()
        self.result_futures = []
        self.exception_futures = []
        self.cancelled_futures = []

    def add_result(self, future):
        self.result_futures.append(future)

    def add_exception(self, future):
        self.exception_futures.append(future)

    def add_cancelled(self, future):
        self.cancelled_futures.append(future)
    
class _FirstCompletedWaiter(_Waiter):
    """Used by wait(return_when=FIRST_COMPLETED)."""

    def add_result(self, future):
        super().add_result(future)
        self.event.set()

    def add_exception(self, future):
        super().add_exception(future)
        self.event.set()

    def add_cancelled(self, future):
        super().add_cancelled(future)
        self.event.set()

class _AllCompletedWaiter(_Waiter):
    """Used by wait(return_when=FIRST_EXCEPTION and ALL_COMPLETED)."""

    def __init__(self, num_pending_calls, stop_on_exception):
        self.num_pending_calls = num_pending_calls
        self.stop_on_exception = stop_on_exception
        super().__init__()

    def _XXX(self):
        self.num_pending_calls -= 1
        if not self.num_pending_calls:
            self.event.set()

    def add_result(self, future):
        super().add_result(future)
        self._XXX()

    def add_exception(self, future):
        super().add_exception(future)
        if self.stop_on_exception:
            self.event.set()
        else:
            self._XXX()

    def add_cancelled(self, future):
        super().add_cancelled(future)
        self._XXX()

class YYY(object):
    def __init__(self, futures):
        self.futures = sorted(futures, key=id)

    def __enter__(self):
        for future in self.futures:
            future._condition.acquire()

    def __exit__(self, *args):
        for future in self.futures:
            future._condition.release()

def iter_as_completed(fs, timeout=None):
    if timeout is not None:
        end_time = timeout + time.time()

    pending = set(fs)

    while pending:
        if timeout is None:
            wait_timeout = None
        else:
            wait_timeout = end_time - time.time()
            if wait_timeout < 0:
                raise TimeoutError()

        print('HERE 2')
        # TODO(brian@sweetapp.com): wait() involves a lot of setup and
        # tear-down - check to see if that makes this implementation
        # unreasonably expensive.
        completed, pending = wait(pending,
                                  timeout=wait_timeout,
                                  return_when=FIRST_COMPLETED)

        for future in completed:
            print('HERE 5')
            yield future

def wait(fs, timeout=None, return_when=ALL_COMPLETED):
    """Wait for the futures in the list to complete.

    Args:
        timeout: The maximum number of seconds to wait. If None, then there
            is no limit on the wait time.
        return_when: Indicates when the method should return. The options
            are:

            FIRST_COMPLETED - Return when any future finishes or is
                              cancelled.
            FIRST_EXCEPTION - Return when any future finishes by raising an
                              exception. If no future raises and exception
                              then it is equivalent to ALL_COMPLETED.
            ALL_COMPLETED -   Return when all futures finish or are cancelled.

    Raises:
        TimeoutError: If the wait condition wasn't satisfied before the
            given timeout.
    """
    with YYY(fs):
        finished = set(
                f for f in fs
                if f._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED])
        not_finished = set(fs) - finished

        if (return_when == FIRST_COMPLETED) and finished:
            return finished, not_finished
        elif (return_when == FIRST_EXCEPTION) and finished:
            if any(f for f in finished
                   if not f.cancelled() and f.exception() is not None):
                return finished, not_finished

        if len(finished) == len(fs):
            return finished, not_finished

        if return_when == FIRST_COMPLETED:
            waiter = _FirstCompletedWaiter()
        else:
            pending_count = sum(
                    f._state not in [CANCELLED_AND_NOTIFIED, FINISHED]
                    for f in fs)

            if return_when == FIRST_EXCEPTION:
               waiter = _AllCompletedWaiter(
                        pending_count, stop_on_exception=True)
            elif return_when == ALL_COMPLETED:
                waiter = _AllCompletedWaiter(
                        pending_count, stop_on_exception=False)
            else:
                raise Exception("XXX")

    for f in fs:
        f._waiters.append(waiter)

    waiter.event.wait(timeout)
    for f in fs:
        f._waiters.remove(waiter)

    finished.update(waiter.result_futures)
    finished.update(waiter.exception_futures)
    finished.update(waiter.cancelled_futures)

    return finished, set(fs) - finished

class Future(object):
    """Represents the result of an asynchronous computation."""

    # Transitions into the CANCELLED_AND_NOTIFIED and FINISHED states trigger notifications to the ThreadEventSink
    # belonging to the Future's FutureList and must be made with ThreadEventSink._condition held to prevent a race
    # condition when the transition is made concurrently with the addition of a new _WaitTracker to the ThreadEventSink.
    # Other state transitions need only have the Future._condition held.
    # When ThreadEventSink._condition and Future._condition must both be held then Future._condition is always acquired
    # first.

    def __init__(self):
        """Initializes the future. Should not be called by clients."""
        self._condition = threading.Condition()
        self._state = PENDING
        self._result = None
        self._exception = None
        self._waiters = []

    def __repr__(self):
        with self._condition:
            if self._state == FINISHED:
                if self._exception:
                    return '<Future state=%s raised %s>' % (
                        _STATE_TO_DESCRIPTION_MAP[self._state],
                        self._exception.__class__.__name__)
                else:
                    return '<Future state=%s returned %s>' % (
                        _STATE_TO_DESCRIPTION_MAP[self._state],
                        self._result.__class__.__name__)
            return '<Future state=%s>' % _STATE_TO_DESCRIPTION_MAP[self._state]

    def cancel(self):
        """Cancel the future if possible.

        Returns True if the future was cancelled, False otherwise. A future
        cannot be cancelled if it is running or has already completed.
        """
        with self._condition:
            if self._state in [RUNNING, FINISHED]:
                return False

            if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                self._state = CANCELLED
                self._condition.notify_all()
            return True

    def cancelled(self):
        """Return True if the future has cancelled."""
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]

    def running(self):
        with self._condition:
            return self._state == RUNNING

    def done(self):
        """Return True of the future was cancelled or finished executing."""
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]

    def _cancel(self):
        with self._condition:
            if self._state == CANCELLED:
                self._state = CANCELLED_AND_NOTIFIED
                for waiter in self._waiters:
                    waiter.add_cancelled(self)
                # self._condition.notify_all() is not necessary because 
                # self.cancel() triggers a notification.
                return True
            return False

    def _set_result(self, result):
        with self._condition:
            self._result = result
            self._state = FINISHED
            for waiter in self._waiters:
                waiter.add_result(self)
            self._condition.notify_all()

    def _set_exception(self, exception):
        with self._condition:
            self._exception = exception
            self._state = FINISHED
            for waiter in self._waiters:
                waiter.add_exception(self)
            self._condition.notify_all()

    def __get_result(self):
        if self._exception:
            raise self._exception
        else:
            return self._result

    def result(self, timeout=None):
        """Return the result of the call that the future represents.

        Args:
            timeout: The number of seconds to wait for the result if the future
                isn't done. If None, then there is no limit on the wait time.

        Returns:
            The result of the call that the future represents.

        Raises:
            CancelledError: If the future was cancelled.
            TimeoutError: If the future didn't finish executing before the given
                timeout.
            Exception: If the call raised then that exception will be raised.
        """
        with self._condition:
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self.__get_result()

            self._condition.wait(timeout)

            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self.__get_result()
            else:
                raise TimeoutError()

    def exception(self, timeout=None):
        """Return the exception raised by the call that the future represents.

        Args:
            timeout: The number of seconds to wait for the exception if the
                future isn't done. If None, then there is no limit on the wait
                time.

        Returns:
            The exception raised by the call that the future represents or None
            if the call completed without raising.

        Raises:
            CancelledError: If the future was cancelled.
            TimeoutError: If the future didn't finish executing before the given
                timeout.
        """

        with self._condition:
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self._exception

            self._condition.wait(timeout)

            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                raise CancelledError()
            elif self._state == FINISHED:
                return self._exception
            else:
                raise TimeoutError()

class Executor(object):
    """This is an abstract base class for concrete asynchronous executors."""

    def map(self, fn, *iterables, timeout=None):
        """Returns a iterator equivalent to map(fn, iter).

        Args:
            fn: A callable that will take take as many arguments as there are
                passed iterables.
            timeout: The maximum number of seconds to wait. If None, then there
                is no limit on the wait time.

        Returns:
            An iterator equivalent to: map(func, *iterables) but the calls may
            be evaluated out-of-order.

        Raises:
            TimeoutError: If the entire result iterator could not be generated
                before the given timeout.
            Exception: If fn(*args) raises for any values.
        """
        if timeout is not None:
            end_time = timeout + time.time()

        fs = [self.submit(fn, *args) for args in zip(*iterables)]

        try:
            for future in fs:
                if timeout is None:
                    yield future.result()
                else:
                    yield future.result(end_time - time.time())
        finally:
            for future in fs:
                future.cancel()

    def shutdown(self):
        """Clean-up. No other methods can be called afterwards."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False

