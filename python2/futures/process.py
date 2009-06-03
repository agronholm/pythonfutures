#!/usr/bin/env python

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

_thread_references = set()
_shutdown = False

def _python_exit():
    global _shutdown
    _shutdown = True
    for thread_reference in _thread_references:
        thread = thread_reference()
        if thread is not None:
            thread.join()

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
    while True:
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
                continue
            else:
                work_item.future._condition.acquire()
                work_item.future._state = RUNNING
                work_item.future._condition.release()
                call_queue.put(_CallItem(work_id, work_item.call), block=True)
                if call_queue.full():
                    return

def _result(executor_reference,
            pending_work_items,
            work_ids_queue,
            call_queue,
            result_queue,
            shutdown_process_event):
    while True:
        _add_call_item_to_queue(pending_work_items,
                                work_ids_queue,
                                call_queue)
        try:
            result_item = result_queue.get(block=True, timeout=0.1)
        except Queue.Empty:
            executor = executor_reference()
            if _shutdown or executor is None or executor._shutdown_thread:
                shutdown_process_event.set()
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
        if max_processes is None:
            max_processes = multiprocessing.cpu_count()

        self._max_processes = max_processes
        # Make the call queue slightly larger than the number of processes to
        # prevent the worker processes from starving but to make future.cancel()
        # responsive.
        self._call_queue = multiprocessing.Queue(self._max_processes + 1)
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

    def _adjust_process_count(self):
        if self._queue_management_thread is None:
            self._queue_management_thread = threading.Thread(
                    target=_result,
                    args=(weakref.ref(self),
                          self._pending_work_items,
                          self._work_ids,
                          self._call_queue,
                          self._result_queue,
                          self._shutdown_process_event))
            self._queue_management_thread.setDaemon(True)
            self._queue_management_thread.start()
            _thread_references.add(weakref.ref(self._queue_management_thread))

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