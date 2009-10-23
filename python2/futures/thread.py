# Copyright 2009 Brian Quinlan. All Rights Reserved. See LICENSE file.

"""Implements ThreadPoolExecutor."""

__author__ = 'Brian Quinlan (brian@sweetapp.com)'

from futures._base import (PENDING, RUNNING, CANCELLED,
                           CANCELLED_AND_NOTIFIED, FINISHED,
                           ALL_COMPLETED,
                           LOGGER,
                           set_future_exception, set_future_result,
                           Executor, Future, FutureList, ThreadEventSink)
import atexit
import Queue
import threading
import weakref

# Workers are created as daemon threads. This is done to allow the interpreter
# to exit when there are still idle threads in a ThreadPoolExecutor's thread
# pool (i.e. shutdown() was not called). However, allowing workers to die with
# the interpreter has two undesirable properties:
#   - The workers would still be running during interpretor shutdown,
#     meaning that they would fail in unpredictable ways.
#   - The workers could be killed while evaluating a work item, which could
#     be bad if the function being evaluated has external side-effects e.g.
#     writing to a file.
#
# To work around this problem, an exit handler is installed which tells the
# workers to exit when their work queues are empty and then waits until they
# finish.

_thread_references = set()  # Weakrefs to every active worker thread.
_shutdown = False           # Indicates that the interpreter is shutting down.

def _python_exit():
    global _shutdown
    _shutdown = True
    for thread_reference in _thread_references:
        thread = thread_reference()
        if thread is not None:
            thread.join()

def _remove_dead_thread_references():
    """Remove inactive threads from _thread_references.

    Should be called periodically to prevent thread objects from accumulating in
    scenarios such as:
    >>> while True:
    >>> ...    t = ThreadPoolExecutor(max_threads=5)
    >>> ...    t.map(int, ['1', '2', '3', '4', '5'])
    """
    for thread_reference in set(_thread_references):
        if thread_reference() is None:
            _thread_references.discard(thread_reference)

atexit.register(_python_exit)

class _WorkItem(object):
    def __init__(self, call, future, completion_tracker):
        self.call = call
        self.future = future
        self.completion_tracker = completion_tracker

    def run(self):
        self.future._condition.acquire()
        try:
            if self.future._state == PENDING:
                self.future._state = RUNNING
            elif self.future._state == CANCELLED:
                self.completion_tracker._condition.acquire()
                try:
                    self.future._state = CANCELLED_AND_NOTIFIED
                    self.completion_tracker.add_cancelled()
                    return
                finally:
                    self.completion_tracker._condition.release()
            else:
                LOGGER.critical('Future %s in unexpected state: %d',
                                id(self.future),
                                self.future._state)
                return
        finally:
            self.future._condition.release()

        try:
            result = self.call()
        except Exception, e:
            set_future_exception(self.future, self.completion_tracker, e)
        else:
            set_future_result(self.future, self.completion_tracker, result)

def _worker(executor_reference, work_queue):
    try:
        while True:
            try:
                work_item = work_queue.get(block=True, timeout=0.1)
            except Queue.Empty:
                executor = executor_reference()
                # Exit if:
                #   - The interpreter is shutting down OR
                #   - The executor that owns the worker has been collected OR
                #   - The executor that owns the worker has been shutdown.
                if _shutdown or executor is None or executor._shutdown:
                    return
                del executor
            else:
                work_item.run()
    except Exception, e:
        LOGGER.critical('Exception in worker', exc_info=True)

class ThreadPoolExecutor(Executor):
    def __init__(self, max_threads):
        """Initializes a new ThreadPoolExecutor instance.

        Args:
            max_threads: The maximum number of threads that can be used to
                execute the given calls.
        """
        _remove_dead_thread_references()

        self._max_threads = max_threads
        self._work_queue = Queue.Queue()
        self._threads = set()
        self._shutdown = False
        self._shutdown_lock = threading.Lock()

    def _adjust_thread_count(self):
        for _ in range(len(self._threads),
                       min(self._max_threads, self._work_queue.qsize())):
            t = threading.Thread(target=_worker,
                                 args=(weakref.ref(self), self._work_queue))
            t.setDaemon(True)
            t.start()
            self._threads.add(t)
            _thread_references.add(weakref.ref(t))

    def run_to_futures(self, calls, timeout=None, return_when=ALL_COMPLETED):
        self._shutdown_lock.acquire()
        try:
            if self._shutdown:
                raise RuntimeError('cannot run new futures after shutdown')

            futures = []
            event_sink = ThreadEventSink()
            for index, call in enumerate(calls):
                f = Future(index)
                w = _WorkItem(call, f, event_sink)
                self._work_queue.put(w)
                futures.append(f)
    
            self._adjust_thread_count()
            fl = FutureList(futures, event_sink)
            fl.wait(timeout=timeout, return_when=return_when)
            return fl
        finally:
            self._shutdown_lock.release()
    run_to_futures.__doc__ = Executor.run_to_futures.__doc__

    def shutdown(self):
        self._shutdown_lock.acquire()
        try:
            self._shutdown = True
        finally:
            self._shutdown_lock.release()
    shutdown.__doc__ = Executor.shutdown.__doc__
