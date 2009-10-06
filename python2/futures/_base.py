# Copyright 2009 Brian Quinlan. All Rights Reserved. See LICENSE file.

__author__ = 'Brian Quinlan (brian@sweetapp.com)'

import logging
import threading
import time

try:
    from functools import partial
except ImportError:
    def partial(func, *args, **keywords):
        def newfunc(*fargs, **fkeywords):
            newkeywords = keywords.copy()
            newkeywords.update(fkeywords)
            return func(*(args + fargs), **newkeywords)
        newfunc.func = func
        newfunc.args = args
        newfunc.keywords = keywords
        return newfunc

# The "any" and "all" builtins weren't introduced until Python 2.5.
try:
    any
except NameError:
    def any(iterable):
        for element in iterable:
            if element:
                return True
        return False

try:
    all
except NameError:
    def all(iterable):
        for element in iterable:
            if not element:
                return False
        return True

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

def set_future_exception(future, event_sink, exception):
    """Sets a future as having terminated with an exception.
    
    This function should only be used within the futures package.

    Args:
        future: The Future that finished with an exception.
        event_sink: The ThreadEventSink accociated with the Future's FutureList.
            The event_sink will be notified of the Future's completion, which
            may unblock some clients that have called FutureList.wait().
        exception: The expection that executing the Future raised.
    """
    future._condition.acquire()
    try:
        future._exception = exception
        event_sink._condition.acquire()
        try:
            future._state = FINISHED
            event_sink.add_exception()
        finally:
            event_sink._condition.release()

        future._condition.notifyAll()
    finally:
        future._condition.release()

def set_future_result(future, event_sink, result):
    """Sets a future as having terminated without exception.
    
    This function should only be used within the futures package.

    Args:
        future: The Future that completed.
        event_sink: The ThreadEventSink accociated with the Future's FutureList.
            The event_sink will be notified of the Future's completion, which
            may unblock some clients that have called FutureList.wait().
        result: The value returned by the Future.
    """
    future._condition.acquire()
    try:
        future._result = result
        event_sink._condition.acquire()
        try:
            future._state = FINISHED
            event_sink.add_result()
        finally:
            event_sink._condition.release()

        future._condition.notifyAll()
    finally:
        future._condition.release()

class Error(Exception):
    pass

class CancelledError(Error):
    pass

class TimeoutError(Error):
    pass

class _WaitTracker(object):
    """Provides the event that FutureList.wait(...) blocks on.

    """
    def __init__(self):
        self.event = threading.Event()

    def add_result(self):
        raise NotImplementedError()

    def add_exception(self):
        raise NotImplementedError()

    def add_cancelled(self):
        raise NotImplementedError()

class _FirstCompletedWaitTracker(_WaitTracker):
    """Used by wait(return_when=FIRST_COMPLETED)."""

    def add_result(self):
        self.event.set()

    def add_exception(self):
        self.event.set()

    def add_cancelled(self):
        self.event.set()

class _AllCompletedWaitTracker(_WaitTracker):
    """Used by wait(return_when=FIRST_EXCEPTION and ALL_COMPLETED)."""

    def __init__(self, num_pending_calls, stop_on_exception):
        self.num_pending_calls = num_pending_calls
        self.stop_on_exception = stop_on_exception
        _WaitTracker.__init__(self)

    def add_result(self):
        self.num_pending_calls -= 1
        if not self.num_pending_calls:
            self.event.set()

    def add_exception(self):
        if self.stop_on_exception:
            self.event.set()
        else:
            self.add_result()

    def add_cancelled(self):
        self.add_result()

class ThreadEventSink(object):
    """Forwards events to many _WaitTrackers.

    Each FutureList has a ThreadEventSink and each call to FutureList.wait()
    causes a new _WaitTracker to be added to the ThreadEventSink. This design
    allows many threads to call FutureList.wait() on the same FutureList with
    different arguments.

    This class should not be used by clients.
    """
    def __init__(self):
        self._condition = threading.Lock()
        self._waiters = []

    def add(self, e):
        self._waiters.append(e)

    def remove(self, e):
        self._waiters.remove(e)

    def add_result(self):
        for waiter in self._waiters:
            waiter.add_result()

    def add_exception(self):
        for waiter in self._waiters:
            waiter.add_exception()

    def add_cancelled(self):
        for waiter in self._waiters:
            waiter.add_cancelled()

class Future(object):
    """Represents the result of an asynchronous computation."""

    def __init__(self, index):
        """Initializes the future. Should not be called by clients."""
        self._condition = threading.Condition()
        self._state = PENDING
        self._result = None
        self._exception = None
        self._index = index

    def __repr__(self):
        self._condition.acquire()
        try:
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
        finally:
            self._condition.release()

    @property
    def index(self):
        """The index of the future in its FutureList."""
        return self._index

    def cancel(self):
        """Cancel the future if possible.

        Returns True if the future was cancelled, False otherwise. A future
        cannot be cancelled if it is running or has already completed.
        """
        self._condition.acquire()
        try:
            if self._state in [RUNNING, FINISHED]:
                return False

            if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                self._state = CANCELLED
                self._condition.notify_all()
            return True
        finally:
            self._condition.release()

    def cancelled(self):
        """Return True if the future has cancelled."""
        self._condition.acquire()
        try:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]
        finally:
            self._condition.release()

    def running(self):
        self._condition.acquire()
        try:
            return self._state == RUNNING
        finally:
            self._condition.release()

    def done(self):
        """Return True of the future was cancelled or finished executing."""
        self._condition.acquire()
        try:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]
        finally:
            self._condition.release()

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
        self._condition.acquire()
        try:
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
        finally:
            self._condition.release()

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

        self._condition.acquire()
        try:
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
        finally:
            self._condition.release()

class FutureList(object):
    def __init__(self, futures, event_sink):
        """Initializes the FutureList. Should not be called by clients."""
        self._futures = futures
        self._event_sink = event_sink

    def wait(self, timeout=None, return_when=ALL_COMPLETED):
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
                ALL_COMPLETED - Return when all futures finish or are cancelled.
                RETURN_IMMEDIATELY - Return without waiting (this is not likely
                                     to be a useful option but it is there to
                                     be symmetrical with the
                                     executor.run_to_futures() method.

        Raises:
            TimeoutError: If the wait condition wasn't satisfied before the
                given timeout.
        """
        if return_when == RETURN_IMMEDIATELY:
            return

        # Futures cannot change state without this condition being held.
        self._event_sink._condition.acquire()
        try:
            # Make a quick exit if every future is already done. This check is
            # necessary because, if every future is in the
            # CANCELLED_AND_NOTIFIED or FINISHED state then the WaitTracker will
            # never receive any events.
            if all(f._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]
                   for f in self):
                return

            if return_when == FIRST_COMPLETED:
                completed_tracker = _FirstCompletedWaitTracker()
            else:
                # Calculate how many events are expected before every future
                # is complete. This can be done without holding the futures'
                # locks because a future cannot transition itself into either
                # of the states being looked for.
                pending_count = sum(
                        f._state not in [CANCELLED_AND_NOTIFIED, FINISHED]
                        for f in self)

                if return_when == FIRST_EXCEPTION:
                    completed_tracker = _AllCompletedWaitTracker(
                            pending_count, stop_on_exception=True)
                elif return_when == ALL_COMPLETED:
                    completed_tracker = _AllCompletedWaitTracker(
                            pending_count, stop_on_exception=False)

            self._event_sink.add(completed_tracker)
        finally:
            self._event_sink._condition.release()

        try:
            completed_tracker.event.wait(timeout)
        finally:
            self._event_sink.remove(completed_tracker)

    def cancel(self, timeout=None):
        """Cancel the futures in the list.

        Args:
            timeout: The maximum number of seconds to wait. If None, then there
                is no limit on the wait time.

        Raises:
            TimeoutError: If all the futures were not finished before the
                given timeout.
        """
        for f in self:
            f.cancel()
        self.wait(timeout=timeout, return_when=ALL_COMPLETED)
        if any(not f.done() for f in self):
            raise TimeoutError()

    def has_running_futures(self):
        """Returns True if any futures in the list are still running."""
        return any(self.running_futures())

    def has_cancelled_futures(self):
        """Returns True if any futures in the list were cancelled."""
        return any(self.cancelled_futures())

    def has_done_futures(self):
        """Returns True if any futures in the list are finished or cancelled."""
        return any(self.done_futures())

    def has_successful_futures(self):
        """Returns True if any futures in the list finished without raising."""
        return any(self.successful_futures())

    def has_exception_futures(self):
        """Returns True if any futures in the list finished by raising."""
        return any(self.exception_futures())

    def cancelled_futures(self):
        """Returns all cancelled futures in the list."""
        return (f for f in self
                if f._state in [CANCELLED, CANCELLED_AND_NOTIFIED])
  
    def done_futures(self):
        """Returns all futures in the list that are finished or cancelled."""
        return (f for f in self
                if f._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED])

    def successful_futures(self):
        """Returns all futures in the list that finished without raising."""
        return (f for f in self
                if f._state == FINISHED and f._exception is None)
  
    def exception_futures(self):
        """Returns all futures in the list that finished by raising."""
        return (f for f in self
                if f._state == FINISHED and f._exception is not None)
  
    def running_futures(self):
        """Returns all futures in the list that are still running."""
        return (f for f in self if f._state == RUNNING)

    def __len__(self):
        return len(self._futures)

    def __getitem__(self, i):
        return self._futures[i]

    def __iter__(self):
        return iter(self._futures)

    def __contains__(self, future):
        return future in self._futures

    def __repr__(self):
        states = dict([(state, 0) for state in _FUTURE_STATES])
        for f in self:
            states[f._state] += 1

        return ('<FutureList #futures=%d '
                '[#pending=%d #cancelled=%d #running=%d #finished=%d]>' % (
                len(self),
                states[PENDING],
                states[CANCELLED] + states[CANCELLED_AND_NOTIFIED],
                states[RUNNING],
                states[FINISHED]))

class Executor(object):
    """This is an abstract base class for concrete asynchronous executors."""
    def run_to_futures(self, calls, timeout=None, return_when=ALL_COMPLETED):
        """Return a list of futures representing the given calls.

        Args:
            calls: A sequence of callables that take no arguments. These will
                be bound to Futures and returned.
            timeout: The maximum number of seconds to wait. If None, then there
                is no limit on the wait time.
            return_when: Indicates when the method should return. The options
                are:

                FIRST_COMPLETED - Return when any future finishes or is
                                  cancelled.
                FIRST_EXCEPTION - Return when any future finishes by raising an
                                  exception. If no future raises and exception
                                  then it is equivalent to ALL_COMPLETED.
                ALL_COMPLETED - Return when all futures finish or are cancelled.
                RETURN_IMMEDIATELY - Return without waiting.

        Returns:
            A FutureList containing Futures for the given calls.
        """
        raise NotImplementedError()

    def run_to_results(self, calls, timeout=None):
        """Returns a iterator of the results of the given calls.

        Args:
            calls: A sequence of callables that take no arguments. These will
                be called and their results returned.
            timeout: The maximum number of seconds to wait. If None, then there
                is no limit on the wait time.

        Returns:
            An iterator over the results of the given calls. Equivalent to:
            (call() for call in calls) but the calls may be evaluated
            out-of-order.

        Raises:
            TimeoutError: If all the given calls were not completed before the
                given timeout.
            Exception: If any call() raises.
        """
        if timeout is not None:
            end_time = timeout + time.time()

        fs = self.run_to_futures(calls, return_when=RETURN_IMMEDIATELY)

        try:
            for future in fs:
                if timeout is None:
                    yield future.result()
                else:
                    yield future.result(end_time - time.time())
        except Exception, e:
            # Python 2.4 and earlier don't allow yield statements in
            # try/finally blocks
            try:
                fs.cancel(timeout=0)
            except TimeoutError:
                pass
            raise e

    def map(self, func, *iterables, **kwargs):
        """Returns a iterator equivalent to map(fn, iter).

        Args:
            func: A callable that will take take as many arguments as there
                are passed iterables.
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
        timeout = kwargs.get('timeout') or None
        calls = [partial(func, *args) for args in zip(*iterables)]
        return self.run_to_results(calls, timeout=timeout)

    def shutdown(self):
        """Clean-up. No other methods can be called afterwards."""
        raise NotImplementedError()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
