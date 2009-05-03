#!/usr/bin/env python

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

        self.future._state = _RUNNING
        try:
            r = self.call()
        except BaseException as e:
            with self.future._condition:
                self.future._exception = e
                self.future._state = _FINISHED
                self.future._condition.notify_all()
            self.completion_tracker.add_exception()
        else:
            with self.future._condition:
                self.future._result = r
                self.future._state = _FINISHED
                self.future._condition.notify_all()
            self.completion_tracker.add_result()

class XXX:
    def wait(self, timeout=None, run_until=ALL_COMPLETED):
        
        pass

class ProcessPoolExecutor(object):
    def __init__(self, max_processes):
        self._max_processes = max_processes
        self._work_queue = multiprocessing.Queue()
        self._processes = set()
        self._shutdown = False
        self._lock = threading.Lock()
        self._queue_count = 0
        self._pending_futures = {}

    def _(self):
        while True:
            try:
                result_item = self._result_queue.get(block=True,
                                                     timeout=0.1)
            except multiprocessing.TimeoutError:
                if self._shutdown:
                    return
            else:
                completion_tracker, future = self._pending_futures[
                        result_item.index]
     
                if result_item.exception:
                    with future._condition:
                        future._exception = result_item.exception
                        future._state = _FINISHED
                        future._condition.notify_all()
                    completion_tracker.add_exception()
                else:
                    with future._condition:
                        future._result = result_item.result
                        future._state = _FINISHED
                        future._condition.notify_all()
                    completion_tracker.add_result()

                

    def _adjust_process_count(self):
        
    def run(self, calls, timeout=None, run_until=ALL_COMPLETED):
        with self._lock:
            if self._shutdown:
                raise RuntimeError()

            futures = []
            event_sink = _ThreadEventSink()
            for call in calls:
                f = Future()
                w = _WorkItem(call, f, event_sink)
                self._work_queue.put(w)
                futures.append(f)
                self._queue_count += 1
    
            print('futures:', futures)
            self._adjust_process_count()
            fl = FutureList(futures, event_sink)
            fl.wait(timeout=timeout, run_until=run_until)
            return fl
