import functools
import logging
import threading
import time

FIRST_COMPLETED = 0
FIRST_EXCEPTION = 1
ALL_COMPLETED = 2
RETURN_IMMEDIATELY = 3

# Possible future states
PENDING = 0
RUNNING = 1
CANCELLED = 2               # The future was cancelled...
CANCELLED_AND_NOTIFIED = 3  # ...and .add_cancelled() was called.
FINISHED = 4

FUTURE_STATES = [
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

LOGGER = logging.getLogger("futures")
_handler = logging.StreamHandler()
LOGGER.addHandler(_handler)
del _handler

def set_future_exception(future, event_sink, exception):
    with future._condition:
        future._exception = exception
        with event_sink._condition:
            future._state = FINISHED
            event_sink.add_exception()
        future._condition.notify_all()

def set_future_result(future, event_sink, result):
    with future._condition:
        future._result = result
        with event_sink._condition:
            future._state = FINISHED
            event_sink.add_result()
        future._condition.notify_all()

class CancelledError(Exception):
    pass

class TimeoutError(Exception):
    pass

class Future(object):
    def __init__(self):
        self._condition = threading.Condition()
        self._state = PENDING
        self._result = None
        self._exception = None

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
        with self._condition:
            if self._state in [RUNNING, FINISHED]:
                return False

            if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                self._state = CANCELLED
                self._condition.notify_all()
            return True

    def cancelled(self):
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]

    def done(self):
        with self._condition:
            return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]

    def __get_result(self):
        if self._exception:
            raise self._exception
        else:
            return self._result

    def result(self, timeout=None):
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

class _FirstCompletedWaitTracker(object):
    def __init__(self):
        self.event = threading.Event()

    def add_result(self):
        self.event.set()

    def add_exception(self):
        self.event.set()

    def add_cancelled(self):
        self.event.set()

class _AllCompletedWaitTracker(object):
    def __init__(self, pending_calls, stop_on_exception):
        self.pending_calls = pending_calls
        self.stop_on_exception = stop_on_exception
        self.event = threading.Event()

    def add_result(self):
        self.pending_calls -= 1
        if not self.pending_calls:
            self.event.set()

    def add_exception(self):
        if self.stop_on_exception:
            self.event.set()
        else:
            self.add_result()

    def add_cancelled(self):
        self.add_result()

class ThreadEventSink(object):
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

class FutureList(object):
    def __init__(self, futures, event_sink):
        self._futures = futures
        self._event_sink = event_sink

    def wait(self, timeout=None, return_when=ALL_COMPLETED):
        if return_when == RETURN_IMMEDIATELY:
            return

        with self._event_sink._condition:
            # Make a quick exit if every future is already done. This check is
            # necessary because, if every future is in the
            # CANCELLED_AND_NOTIFIED or FINISHED state then the WaitTracker will
            # never receive any 
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

        try:
            completed_tracker.event.wait(timeout)
        finally:
            self._event_sink.remove(completed_tracker)

    def cancel(self, timeout=None):
        for f in self:
            f.cancel()
        self.wait(timeout=timeout, return_when=ALL_COMPLETED)
        if any(not f.done() for f in self):
            raise TimeoutError()

    def has_running_futures(self):
        return any(self.running_futures())

    def has_cancelled_futures(self):
        return any(self.cancelled_futures())

    def has_done_futures(self):
        return any(self.done_futures())

    def has_successful_futures(self):
        return any(self.successful_futures())

    def has_exception_futures(self):
        return any(self.exception_futures())

    def has_running_futures(self):
        return any(self.running_futures())
        
    def cancelled_futures(self):
        return (f for f in self
                if f._state in [CANCELLED, CANCELLED_AND_NOTIFIED])
  
    def done_futures(self):
        return (f for f in self
                if f._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED])

    def successful_futures(self):
        return (f for f in self
                if f._state == FINISHED and f._exception is None)
  
    def exception_futures(self):
        return (f for f in self
                if f._state == FINISHED and f._exception is not None)
  
    def running_futures(self):
        return (f for f in self if f._state == RUNNING)

    def __getitem__(self, i):
        return self._futures[i]

    def __len__(self):
        return len(self._futures)

    def __iter__(self):
        return iter(self._futures)

    def __contains__(self, f):
        return f in self._futures

    def __repr__(self):
        states = {state: 0 for state in FUTURE_STATES}
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
    def run(self, calls, timeout=None, return_when=ALL_COMPLETED):
        raise NotImplementedError()

    def runXXX(self, calls, timeout=None):
        """Execute the given calls and

        Arguments:
        calls: A sequence of functions that will be called without arguments
               and whose results with be returned.
        timeout: The maximum number of seconds to wait for the complete results.
                 None indicates that there is no timeout.

        Yields:
            The results of the given calls in the order that they are given.

        Exceptions:
            TimeoutError: if it takes more than timeout 
        """
        if timeout is not None:
            end_time = timeout + time.time()

        fs = self.run(calls, return_when=RETURN_IMMEDIATELY)

        try:
            for future in fs:
                if timeout is None:
                    yield future.result()
                else:
                    yield future.result(end_time - time.time())
        finally:
            try:
                fs.cancel(timeout=0)
            except TimeoutError:
                pass

    def map(self, fn, iter, timeout=None):
        calls = [functools.partial(fn, a) for a in iter]
        return self.runXXX(calls, timeout)

    def shutdown(self):
        raise NotImplementedError()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
