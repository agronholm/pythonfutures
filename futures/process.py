#!/usr/bin/env python

from futures._base import RUNNING, FINISHED, Executor, ALL_COMPLETED, ThreadEventSink, Future, FutureList
import queue
import multiprocessing
import threading

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
        except queue.Empty:
            if shutdown.is_set():
                return
        else:
            try:
                r = call_item.call()
            except BaseException as e:
                result_queue.put(_ResultItem(call_item.work_id,
                                             exception=e))
            else:
                result_queue.put(_ResultItem(call_item.work_id,
                                             result=r))

class ProcessPoolExecutor(Executor):
    def __init__(self, max_processes=None):
        if max_processes is None:
            try:
                max_processes = multiprocessing.cpu_count()
            except NotImplementedError:
                max_processes = 16
            
        self._max_processes = max_processes
        self._call_queue = multiprocessing.Queue(self._max_processes + 1)
        self._result_queue = multiprocessing.Queue()
        self._work_ids = queue.Queue()
        self._queue_management_thread = None
        self._processes = set()
        self._shutdown = False
        self._shutdown_process_event = multiprocessing.Event()
        self._lock = threading.Lock()
        self._queue_count = 0
        self._pending_work_items = {}


    def _add_call_item_to_queue(self):
        while True:
            try:
                work_id = self._work_ids.get(block=False)
            except queue.Empty:
                return
            else:
                work_item = self._pending_work_items[work_id]
    
                if work_item.future.cancelled():
                    with work_item.future._condition:
                        work_item.future._condition.notify_all()
                    work_item.completion_tracker.add_cancelled()
                    continue
                else:
                    with work_item.future._condition:
                        work_item.future._state = RUNNING

                    self._call_queue.put(_CallItem(work_id, work_item.call),
                                         block=True)
                    if self._call_queue.full():
                        return

    def _result(self):
        while True:
            self._add_call_item_to_queue()
            try:
                result_item = self._result_queue.get(block=True,
                                                     timeout=0.1)
            except queue.Empty:
                if self._shutdown and not self._pending_work_items:
                    self._shutdown_process_event.set()
                    return
            else:
                work_item = self._pending_work_items[result_item.work_id]
                del self._pending_work_items[result_item.work_id]

                if result_item.exception:
                    with work_item.future._condition:
                        work_item.future._exception = result_item.exception
                        work_item.future._state = FINISHED
                        work_item.future._condition.notify_all()
                    work_item.completion_tracker.add_exception()
                else:
                    with work_item.future._condition:
                        work_item.future._result = result_item.result
                        work_item.future._state = FINISHED
                        work_item.future._condition.notify_all()
                    work_item.completion_tracker.add_result()

    def _adjust_process_count(self):
        if self._queue_management_thread is None:
            self._queue_management_thread = threading.Thread(
                    target=self._result)
            self._queue_management_thread.daemon = True
            self._queue_management_thread.start()

        for _ in range(len(self._processes), self._max_processes):
            p = multiprocessing.Process(
                    target=_process_worker,
                    args=(self._call_queue,
                          self._result_queue,
                          self._shutdown_process_event))
            p.daemon = True
            p.start()
            self._processes.add(p)

    def run(self, calls, timeout=None, run_until=ALL_COMPLETED):
        with self._lock:
            if self._shutdown:
                raise RuntimeError()

            futures = []
            event_sink = ThreadEventSink()
            self._queue_count
            for call in calls:
                f = Future()
                self._pending_work_items[self._queue_count] = _WorkItem(
                        call, f, event_sink)
                self._work_ids.put(self._queue_count)
                futures.append(f)
                self._queue_count += 1

            self._adjust_process_count()
            fl = FutureList(futures, event_sink)
            fl.wait(timeout=timeout, run_until=run_until)
            return fl

    def shutdown(self):
        with self._lock:
            self._shutdown = True
