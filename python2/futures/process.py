# Copyright 2009 Brian Quinlan. All Rights Reserved. See LICENSE file.

"""Implements ProcessPoolExecutor.

The follow diagram and text describe the data-flow through the system:

|======================= In-process =====================|== Out-of-process ==|

+----------+     +----------+       +--------+     +-----------+    +---------+
|          |  => | Work Ids |    => |        |  => | Call Q    | => |         |
|          |     +----------+       |        |     +-----------+    |         |
|          |     | ...      |       |        |     | ...       |    |         |
|          |     | 6        |       |        |     | 5, call() |    |         |
|          |     | 7        |       |        |     | ...       |    |         |
| Process  |     | ...      |       | Local  |     +-----------+    | Process |
|  Pool    |     +----------+       | Worker |                      |  #1..n  |
| Executor |                        | Thread |                      |         |
|          |     +----------- +     |        |     +-----------+    |         |
|          | <=> | Work Items | <=> |        | <=  | Result Q  | <= |         |
|          |     +------------+     |        |     +-----------+    |         |
|          |     | 6: call()  |     |        |     | ...       |    |         |
|          |     |    future  |     |        |     | 4, result |    |         |
|          |     | ...        |     |        |     | 3, except |    |         |
+----------+     +------------+     +--------+     +-----------+    +---------+

Executor.run_to_futures() called:
- creates a uniquely numbered _WorkItem for each call and adds them to the
  "Work Items" dict
- adds the id of the _WorkItem to the "Work Ids" queue

Local worker thread:
- reads work ids from the "Work Ids" queue and looks up the corresponding
  WorkItem from the "Work Items" dict: if the work item has been cancelled then
  it is simply removed from the dict, otherwise it is repackaged as a
  _CallItem and put in the "Call Q". New _CallItems are put in the "Call Q"
  until "Call Q" is full. NOTE: the size of the "Call Q" is kept small because
  calls placed in the "Call Q" can no longer be cancelled with Future.cancel().
- reads _ResultItems from "Result Q", updates the future stored in the
  "Work Items" dict and deletes the dict entry

Process #1..n:
- reads _CallItems from "Call Q", executes the calls, and puts the resulting
  _ResultItems in "Request Q"
"""
 
__author__ = 'Brian Quinlan (brian@sweetapp.com)'

from futures._base import (PENDING, RUNNING, CANCELLED,
                           CANCELLED_AND_NOTIFIED, FINISHED,
                           ALL_COMPLETED,
                           set_future_exception, set_future_result,
                           Executor, Future, FutureList, ThreadEventSink)
import atexit
import Queue
import multiprocessing
import threading
import weakref

# Workers are created as daemon threads and processes. This is done to allow the
# interpreter to exit when there are still idle processes in a
# ProcessPoolExecutor's process pool (i.e. shutdown() was not called). However,
# allowing workers to die with the interpreter has two undesirable properties:
#   - The workers would still be running during interpretor shutdown,
#     meaning that they would fail in unpredictable ways.
#   - The workers could be killed while evaluating a work item, which could
#     be bad if the function being evaluated has external side-effects e.g.
#     writing to a file.
#
# To work around this problem, an exit handler is installed which tells the
# workers to exit when their work queues are empty and then waits until the
# threads/processes finish.

_thread_references = set()
_shutdown = False

def _python_exit():
    global _shutdown
    _shutdown = True
    for thread_reference in _thread_references:
        thread = thread_reference()
        if thread is not None:
            thread.join()

def _remove_dead_thread_references():
    """Remove inactive threads from _thread_references.

    Should be called periodically to prevent memory leaks in scenarios such as:
    >>> while True:
    >>> ...    t = ThreadPoolExecutor(max_threads=5)
    >>> ...    t.map(int, ['1', '2', '3', '4', '5'])
    """
    for thread_reference in set(_thread_references):
        if thread_reference() is None:
            _thread_references.discard(thread_reference)

# Controls how many more calls than processes will be queued in the call queue.
# A smaller number will mean that processes spend more time idle waiting for
# work while a larger number will make Future.cancel() succeed less frequently
# (Futures in the call queue cannot be cancelled).
EXTRA_QUEUED_CALLS = 1

class _WorkItem(object):
    def __init__(self, call, future, completion_tracker):
        self.call = call
        self.future = future
        self.completion_tracker = completion_tracker

class _ResultItem(object):
    def __init__(self, work_id, exception=None, result=None):
        self.work_id = work_id
        self.exception = exception
        self.result = result

class _CallItem(object):
    def __init__(self, work_id, call):
        self.work_id = work_id
        self.call = call

def _process_worker(call_queue, result_queue, shutdown):
    """Evaluates calls from call_queue and places the results in result_queue.

    This worker is run in a seperate process.

    Args:
        call_queue: A multiprocessing.Queue of _CallItems that will be read and
            evaluated by the worker.
        result_queue: A multiprocessing.Queue of _ResultItems that will written
            to by the worker.
        shutdown: A multiprocessing.Event that will be set as a signal to the
            worker that it should exit when call_queue is empty.
    """
    while True:
        try:
            call_item = call_queue.get(block=True, timeout=0.1)
        except Queue.Empty:
            if shutdown.is_set():
                return
        else:
            try:
                r = call_item.call()
            except Exception, e:
                result_queue.put(_ResultItem(call_item.work_id,
                                             exception=e))
            else:
                result_queue.put(_ResultItem(call_item.work_id,
                                             result=r))

def _add_call_item_to_queue(pending_work_items,
                            work_ids,
                            call_queue):
    """Fills call_queue with _WorkItems from pending_work_items.

    This function never blocks.

    Args:
        pending_work_items: A dict mapping work ids to _WorkItems e.g.
            {5: <_WorkItem...>, 6: <_WorkItem...>, ...}
        work_ids: A queue.Queue of work ids e.g. Queue([5, 6, ...]). Work ids
            are consumed and the corresponding _WorkItems from
            pending_work_items are transformed into _CallItems and put in
            call_queue.
        call_queue: A multiprocessing.Queue that will be filled with _CallItems
            derived from _WorkItems.
    """
    while True:
        if call_queue.full():
            return
        try:
            work_id = work_ids.get(block=False)
        except Queue.Empty:
            return
        else:
            work_item = pending_work_items[work_id]

            if work_item.future.cancelled():
                work_item.future._condition.acquire()
                work_item.future._condition.notify_all()
                work_item.future._condition.release()

                work_item.completion_tracker.add_cancelled()
                del pending_work_items[work_id]
                continue
            else:
                work_item.future._condition.acquire()
                work_item.future._state = RUNNING
                work_item.future._condition.release()
                call_queue.put(_CallItem(work_id, work_item.call), block=True)

def _queue_manangement_worker(executor_reference,
                              processes,
                              pending_work_items,
                              work_ids_queue,
                              call_queue,
                              result_queue,
                              shutdown_process_event):
    """Manages the communication between this process and the worker processes.

    This function is run in a local thread.

    Args:
        executor_reference: A weakref.ref to the ProcessPoolExecutor that owns
            this thread. Used to determine if the ProcessPoolExecutor has been
            garbage collected and that this function can exit.
        process: A list of the multiprocessing.Process instances used as
            workers.
        pending_work_items: A dict mapping work ids to _WorkItems e.g.
            {5: <_WorkItem...>, 6: <_WorkItem...>, ...}
        work_ids_queue: A queue.Queue of work ids e.g. Queue([5, 6, ...]).
        call_queue: A multiprocessing.Queue that will be filled with _CallItems
            derived from _WorkItems for processing by the process workers.
        result_queue: A multiprocessing.Queue of _ResultItems generated by the
            process workers.
        shutdown_process_event: A multiprocessing.Event used to signal the
            process workers that they should exit when their work queue is
            empty.
    """
    while True:
        _add_call_item_to_queue(pending_work_items,
                                work_ids_queue,
                                call_queue)
        try:
            result_item = result_queue.get(block=True, timeout=0.1)
        except Queue.Empty:
            executor = executor_reference()
            # No more work items can be added if:
            #   - The interpreter is shutting down OR
            #   - The executor that owns this worker has been collected OR
            #   - The executor that owns this worker has been shutdown.
            if _shutdown or executor is None or executor._shutdown_thread:
                # Since no new work items can be added, it is safe to shutdown
                # this thread if there are no pending work items.
                if not pending_work_items:
                    shutdown_process_event.set()

                    # If .join() is not called on the created processes then
                    # some multiprocessing.Queue methods may deadlock on Mac OS
                    # X.
                    for p in processes:
                        p.join()
                    return
            del executor
        else:
            work_item = pending_work_items[result_item.work_id]
            del pending_work_items[result_item.work_id]

            if result_item.exception:
                set_future_exception(work_item.future,
                                     work_item.completion_tracker,
                                     result_item.exception)
            else:
                set_future_result(work_item.future,
                                     work_item.completion_tracker,
                                     result_item.result)

class ProcessPoolExecutor(Executor):
    def __init__(self, max_processes=None):
        """Initializes a new ProcessPoolExecutor instance.

        Args:
            max_processes: The maximum number of processes that can be used to
                execute the given calls. If None or not given then as many
                worker processes will be created as the machine has processors.
        """
        _remove_dead_thread_references()

        if max_processes is None:
            self._max_processes = multiprocessing.cpu_count()
        else:
            self._max_processes = max_processes

        # Make the call queue slightly larger than the number of processes to
        # prevent the worker processes from idling. But don't make it too big
        # because futures in the call queue cannot be cancelled.
        self._call_queue = multiprocessing.Queue(self._max_processes +
                                                 EXTRA_QUEUED_CALLS)
        self._result_queue = multiprocessing.Queue()
        self._work_ids = Queue.Queue()
        self._queue_management_thread = None
        self._processes = set()

        # Shutdown is a two-step process.
        self._shutdown_thread = False
        self._shutdown_process_event = multiprocessing.Event()
        self._shutdown_lock = threading.Lock()
        self._queue_count = 0
        self._pending_work_items = {}

    def _start_queue_management_thread(self):
        if self._queue_management_thread is None:
            self._queue_management_thread = threading.Thread(
                    target=_queue_manangement_worker,
                    args=(weakref.ref(self),
                          self._processes,
                          self._pending_work_items,
                          self._work_ids,
                          self._call_queue,
                          self._result_queue,
                          self._shutdown_process_event))
            self._queue_management_thread.setDaemon(True)
            self._queue_management_thread.start()
            _thread_references.add(weakref.ref(self._queue_management_thread))

    def _adjust_process_count(self):
        for _ in range(len(self._processes), self._max_processes):
            p = multiprocessing.Process(
                    target=_process_worker,
                    args=(self._call_queue,
                          self._result_queue,
                          self._shutdown_process_event))
            p.start()
            self._processes.add(p)

    def run_to_futures(self, calls, timeout=None, return_when=ALL_COMPLETED):
        self._shutdown_lock.acquire()
        try:
            if self._shutdown_thread:
                raise RuntimeError('cannot run new futures after shutdown')

            futures = []
            event_sink = ThreadEventSink()

            for index, call in enumerate(calls):
                f = Future(index)
                self._pending_work_items[self._queue_count] = _WorkItem(
                        call, f, event_sink)
                self._work_ids.put(self._queue_count)
                futures.append(f)
                self._queue_count += 1

            self._start_queue_management_thread()
            self._adjust_process_count()
            fl = FutureList(futures, event_sink)
            fl.wait(timeout=timeout, return_when=return_when)
            return fl
        finally:
            self._shutdown_lock.release()

    def shutdown(self):
        self._shutdown_lock.acquire()
        try:
            self._shutdown_thread = True
        finally:
            self._shutdown_lock.release()

atexit.register(_python_exit)