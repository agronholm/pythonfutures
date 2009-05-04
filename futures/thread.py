#!/usr/bin/env python

from futures._base import RUNNING, FINISHED, Executor, ALL_COMPLETED, ThreadEventSink, Future, FutureList
import queue
import threading

class _WorkItem(object):
    def __init__(self, call, future, completion_tracker):
        self.call = call
        self.future = future
        self.completion_tracker = completion_tracker

    def run(self):
        if self.future.cancelled():
            with self.future._condition:
                self.future._condition.notify_all()
            self.completion_tracker.add_cancelled()
            return

        with self.future._condition:
            self.future._state = RUNNING

        try:
            r = self.call()
        except BaseException as e:
            with self.future._condition:
                self.future._exception = e
                self.future._state = FINISHED
                self.future._condition.notify_all()
            self.completion_tracker.add_exception()
        else:
            with self.future._condition:
                self.future._result = r
                self.future._state = FINISHED
                self.future._condition.notify_all()
            self.completion_tracker.add_result()

class ThreadPoolExecutor(Executor):
    def __init__(self, max_threads):
        self._max_threads = max_threads
        self._work_queue = queue.Queue()
        self._threads = set()
        self._shutdown = False
        self._lock = threading.Lock()

    def _worker(self):
        try:
            while True:
                try:
                    work_item = self._work_queue.get(block=True,
                                                    timeout=0.1)
                except queue.Empty:
                    if self._shutdown:
                        return
                else:
                    work_item.run()
        except BaseException as e:
            print('Out e:', e)

    def _adjust_thread_count(self):
        for _ in range(len(self._threads),
                       min(self._max_threads, self._work_queue.qsize())):
            t = threading.Thread(target=self._worker)
            t.daemon = True
            t.start()
            self._threads.add(t)

    def run(self, calls, timeout=None, run_until=ALL_COMPLETED):
        with self._lock:
            if self._shutdown:
                raise RuntimeError()

            futures = []
            event_sink = ThreadEventSink()
            for call in calls:
                f = Future()
                w = _WorkItem(call, f, event_sink)
                self._work_queue.put(w)
                futures.append(f)
    
            self._adjust_thread_count()
            fl = FutureList(futures, event_sink)
            fl.wait(timeout=timeout, run_until=run_until)
            return fl

    def shutdown(self):
        with self._lock:
            self._shutdown = True
