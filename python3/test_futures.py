import test.support

import unittest
import threading
import time
import multiprocessing

import futures
import futures._base
from futures._base import (
    PENDING, RUNNING, CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED, Future)

def create_future(state=PENDING, exception=None, result=None):
    f = Future(0)
    f._state = state
    f._exception = exception
    f._result = result
    return f

PENDING_FUTURE = create_future(state=PENDING)
RUNNING_FUTURE = create_future(state=RUNNING)
CANCELLED_FUTURE = create_future(state=CANCELLED)
CANCELLED_AND_NOTIFIED_FUTURE = create_future(state=CANCELLED_AND_NOTIFIED)
EXCEPTION_FUTURE = create_future(state=FINISHED, exception=IOError())
SUCCESSFUL_FUTURE = create_future(state=FINISHED, result=42)

class Call(object):
    CALL_LOCKS = {}
    def __init__(self, manual_finish=False, result=42):
        called_event = multiprocessing.Event()
        can_finish = multiprocessing.Event()

        self._result = result
        self._called_event_id = id(called_event)
        self._can_finish_event_id = id(can_finish)

        self.CALL_LOCKS[self._called_event_id] = called_event
        self.CALL_LOCKS[self._can_finish_event_id] = can_finish

        if not manual_finish:
            self._can_finish.set()

    @property
    def _can_finish(self):
        return self.CALL_LOCKS[self._can_finish_event_id]

    @property
    def _called_event(self):
        return self.CALL_LOCKS[self._called_event_id]

    def wait_on_called(self):
        self._called_event.wait()

    def set_can(self):
        self._can_finish.set()

    def called(self):
        return self._called_event.is_set()

    def __call__(self):
        if self._called_event.is_set(): print('called twice')

        self._called_event.set()
        self._can_finish.wait()
        return self._result

    def close(self):
        del self.CALL_LOCKS[self._called_event_id]
        del self.CALL_LOCKS[self._can_finish_event_id]

class ExceptionCall(Call):
    def __call__(self):
        assert not self._called_event.is_set(), 'already called'

        self._called_event.set()
        self._can_finish.wait()
        raise ZeroDivisionError()

class ExecutorShutdownTest(unittest.TestCase):
    def test_run_after_shutdown(self):
        call1 = Call()
        try:
            self.executor.shutdown()
            self.assertRaises(RuntimeError,
                              self.executor.run_to_futures,
                              [call1])
        finally:
            call1.close()

    def _start_some_futures(self):
        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        call3 = Call(manual_finish=True)

        try:
            self.executor.run_to_futures([call1, call2, call3],
                                         return_when=futures.RETURN_IMMEDIATELY)
    
            call1.wait_on_called()
            call2.wait_on_called()
            call3.wait_on_called()
    
            call1.set_can()
            call2.set_can()
            call3.set_can()
        finally:
            call1.close()
            call2.close()
            call3.close()

class ThreadPoolShutdownTest(ExecutorShutdownTest):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=5)

    def tearDown(self):
        self.executor.shutdown()

    def test_threads_terminate(self):
        self._start_some_futures()
        self.assertEqual(len(self.executor._threads), 3)
        self.executor.shutdown()
        for t in self.executor._threads:
            t.join()

    def test_context_manager_shutdown(self):
        with futures.ThreadPoolExecutor(max_threads=5) as e:
            executor = e
            self.assertEqual(list(e.map(abs, range(-5, 5))),
                             [5, 4, 3, 2, 1, 0, 1, 2, 3, 4])

        for t in executor._threads:
            t.join()

class ProcessPoolShutdownTest(ExecutorShutdownTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=5)

    def tearDown(self):
        self.executor.shutdown()

    def test_processes_terminate(self):
        self._start_some_futures()
        self.assertEqual(len(self.executor._processes), 5)
        self.executor.shutdown()
        for p in self.executor._processes:
            p.join()

    def test_context_manager_shutdown(self):
        with futures.ProcessPoolExecutor(max_processes=5) as e:
            executor = e
            self.assertEqual(list(e.map(abs, range(-5, 5))),
                             [5, 4, 3, 2, 1, 0, 1, 2, 3, 4])

        for p in self.executor._processes:
            p.join()

class WaitsTest(unittest.TestCase):
    def test_concurrent_waits(self):
        def wait_for_ALL_COMPLETED():
            fs.wait(return_when=futures.ALL_COMPLETED)
            self.assertTrue(f1.done())
            self.assertTrue(f2.done())
            self.assertTrue(f3.done())
            self.assertTrue(f4.done())
            all_completed.release()

        def wait_for_FIRST_COMPLETED():
            fs.wait(return_when=futures.FIRST_COMPLETED)
            self.assertTrue(f1.done())
            self.assertFalse(f2.done()) # XXX
            self.assertFalse(f3.done())
            self.assertFalse(f4.done())
            first_completed.release()

        def wait_for_FIRST_EXCEPTION():
            fs.wait(return_when=futures.FIRST_EXCEPTION)
            self.assertTrue(f1.done())
            self.assertTrue(f2.done())
            self.assertFalse(f3.done()) # XXX
            self.assertFalse(f4.done())
            first_exception.release()

        all_completed = threading.Semaphore(0)
        first_completed = threading.Semaphore(0)
        first_exception = threading.Semaphore(0)

        call1 = Call(manual_finish=True)
        call2 = ExceptionCall(manual_finish=True)
        call3 = Call(manual_finish=True)
        call4 = Call()

        try:
            fs = self.executor.run_to_futures(
                    [call1, call2, call3, call4],
                    return_when=futures.RETURN_IMMEDIATELY)
            f1, f2, f3, f4 = fs
    
            threads = []
            for wait_test in [wait_for_ALL_COMPLETED,
                              wait_for_FIRST_COMPLETED,
                              wait_for_FIRST_EXCEPTION]:
                t = threading.Thread(target=wait_test)
                t.start()
                threads.append(t)
    
            time.sleep(1)   # give threads enough time to execute wait
    
            call1.set_can()
            first_completed.acquire()
            call2.set_can()        
            first_exception.acquire()
            call3.set_can()
            all_completed.acquire()
    
            self.executor.shutdown()
        finally:
            call1.close()
            call2.close()
            call3.close()
            call4.close()

class ThreadPoolWaitTests(WaitsTest):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown()

class ProcessPoolWaitTests(WaitsTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown()

class CancelTests(unittest.TestCase):
    def test_cancel_states(self):
        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        try:
            fs = self.executor.run_to_futures(
                    [call1, call2, call3, call4],
                    return_when=futures.RETURN_IMMEDIATELY)
            f1, f2, f3, f4 = fs
    
            call1.wait_on_called()
            self.assertEqual(f1.cancel(), False)
            self.assertEqual(f2.cancel(), True)
            self.assertEqual(f4.cancel(), True)
            self.assertEqual(f1.cancelled(), False)
            self.assertEqual(f2.cancelled(), True)
            self.assertEqual(f3.cancelled(), False)
            self.assertEqual(f4.cancelled(), True)
            self.assertEqual(f1.done(), False)
            self.assertEqual(f2.done(), True)
            self.assertEqual(f3.done(), False)
            self.assertEqual(f4.done(), True)
    
            call1.set_can()
            fs.wait(return_when=futures.ALL_COMPLETED)
            self.assertEqual(f1.result(), 42)
            self.assertRaises(futures.CancelledError, f2.result)
            self.assertRaises(futures.CancelledError, f2.exception)
            self.assertEqual(f3.result(), 42)
            self.assertRaises(futures.CancelledError, f4.result)
            self.assertRaises(futures.CancelledError, f4.exception)
    
            self.assertEqual(call2.called(), False)
            self.assertEqual(call4.called(), False)
        finally:
            call1.close()
            call2.close()
            call3.close()
            call4.close()

    def test_wait_for_individual_cancel_while_waiting(self):
        def end_call():
            # Wait until the main thread is waiting on the results of the
            # future.
            time.sleep(1)
            f2.cancel()
            call1.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call()

        try:
            fs = self.executor.run_to_futures(
                    [call1, call2],
                    return_when=futures.RETURN_IMMEDIATELY)
            f1, f2 = fs
    
            call1.wait_on_called()
            t = threading.Thread(target=end_call)
            t.start()
            self.assertRaises(futures.CancelledError, f2.result)
            self.assertRaises(futures.CancelledError, f2.exception)
            t.join()
        finally:
            call1.close()
            call2.close()

    def test_wait_with_already_cancelled_futures(self):
        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        try:
            fs = self.executor.run_to_futures(
                    [call1, call2, call3, call4],
                    return_when=futures.RETURN_IMMEDIATELY)
            f1, f2, f3, f4 = fs
    
            call1.wait_on_called()
            self.assertTrue(f2.cancel())
            self.assertTrue(f3.cancel())
            call1.set_can()
    
            fs.wait(return_when=futures.ALL_COMPLETED)
        finally:
            call1.close()
            call2.close()
            call3.close()
            call4.close()

    def test_cancel_all(self):
        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        try:
            fs = self.executor.run_to_futures(
                    [call1, call2, call3, call4],
                    return_when=futures.RETURN_IMMEDIATELY)
            f1, f2, f3, f4 = fs
    
            call1.wait_on_called()
            self.assertRaises(futures.TimeoutError, fs.cancel, timeout=0)
            call1.set_can()
            fs.cancel()
    
            self.assertFalse(f1.cancelled())
            self.assertTrue(f2.cancelled())
            self.assertTrue(f3.cancelled())
            self.assertTrue(f4.cancelled())
        finally:
            call1.close()
            call2.close()
            call3.close()
            call4.close()

class ThreadPoolCancelTests(CancelTests):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown()

class ProcessPoolCancelTests(WaitsTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown()

class ExecutorTest(unittest.TestCase):
    # Executor.shutdown() and context manager usage is tested by
    # ExecutorShutdownTest.
    def test_run_to_futures(self):
        call1 = Call(result=1)
        call2 = Call(result=2)
        call3 = Call(manual_finish=True)
        call4 = Call()
        call5 = Call()

        try:
            f1, f2, f3, f4, f5 = self.executor.run_to_futures(
                    [call1, call2, call3, call4, call5],
                    return_when=futures.RETURN_IMMEDIATELY)
    
            call3.wait_on_called()

            # ProcessPoolExecutor uses a thread to propogate results into the
            # future. Calling result() ensures that the thread has done its work
            # before doing the next set of checks.
            f1.result()  
            f2.result()

            self.assertTrue(f1.done())
            self.assertFalse(f1.running())
            self.assertEqual(f1.index, 0)
    
            self.assertTrue(f2.done())
            self.assertFalse(f2.running())
            self.assertEqual(f2.index, 1)
    
            self.assertFalse(f3.done())
            self.assertTrue(f3.running())
            self.assertEqual(f3.index, 2)

            # ProcessPoolExecutor may mark some futures as running before they
            # actually are so don't check these ones.
            self.assertFalse(f4.done())
            self.assertEqual(f4.index, 3)
    
            self.assertFalse(f5.done())
            self.assertEqual(f5.index, 4)
        finally:
            call3.set_can()  # Let the call finish executing.
            call1.close()
            call2.close()
            call3.close()
            call4.close()
            call5.close()

    def test_run_to_results(self):
        call1 = Call(result=1)
        call2 = Call(result=2)
        call3 = Call(result=3)
        try:
            self.assertEqual(
                    list(self.executor.run_to_results([call1, call2, call3])),
                    [1, 2, 3])
        finally:
            call1.close()
            call2.close()
            call3.close()

    def test_run_to_results_exception(self):
        call1 = Call(result=1)
        call2 = Call(result=2)
        call3 = ExceptionCall()
        try:
            i = self.executor.run_to_results([call1, call2, call3])
    
            self.assertEqual(i.__next__(), 1)
            self.assertEqual(i.__next__(), 2)
            self.assertRaises(ZeroDivisionError, i.__next__)
        finally:
            call1.close()
            call2.close()
            call3.close()

    def test_run_to_results_timeout(self):
        call1 = Call(result=1)
        call2 = Call(result=2)
        call3 = Call(manual_finish=True)

        try:
            i = self.executor.run_to_results([call1, call2, call3], timeout=1)
            self.assertEqual(i.__next__(), 1)
            self.assertEqual(i.__next__(), 2)
            self.assertRaises(futures.TimeoutError, i.__next__)
            call3.set_can()
        finally:
            call1.close()
            call2.close()
            call3.close()

    def test_map(self):
        self.assertEqual(
                list(self.executor.map(pow, range(10), range(10))),
                list(map(pow, range(10), range(10))))

    def test_map_exception(self):
        i = self.executor.map(divmod, [1, 1, 1, 1], [2, 3, 0, 5])
        self.assertEqual(i.__next__(), (0, 1))
        self.assertEqual(i.__next__(), (0, 1))
        self.assertRaises(ZeroDivisionError, i.__next__)

class ThreadPoolExecutorTest(ExecutorTest):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown()

class ProcessPoolExecutorTest(ExecutorTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown()

class FutureTests(unittest.TestCase):
    # Future.index() is tested by ExecutorTest
    # Future.cancel() is further tested by CancelTests.

    def test_repr(self):
        self.assertEqual(repr(PENDING_FUTURE), '<Future state=pending>')
        self.assertEqual(repr(RUNNING_FUTURE), '<Future state=running>')
        self.assertEqual(repr(CANCELLED_FUTURE), '<Future state=cancelled>')
        self.assertEqual(repr(CANCELLED_AND_NOTIFIED_FUTURE),
                         '<Future state=cancelled>')
        self.assertEqual(repr(EXCEPTION_FUTURE),
                         '<Future state=finished raised IOError>')
        self.assertEqual(repr(SUCCESSFUL_FUTURE),
                         '<Future state=finished returned int>')

        create_future

    def test_cancel(self):
        f1 = create_future(state=PENDING)
        f2 = create_future(state=RUNNING)
        f3 = create_future(state=CANCELLED)
        f4 = create_future(state=CANCELLED_AND_NOTIFIED)
        f5 = create_future(state=FINISHED, exception=IOError())
        f6 = create_future(state=FINISHED, result=5)

        self.assertTrue(f1.cancel())
        self.assertEquals(f1._state, CANCELLED)

        self.assertFalse(f2.cancel())
        self.assertEquals(f2._state, RUNNING)

        self.assertTrue(f3.cancel())
        self.assertEquals(f3._state, CANCELLED)

        self.assertTrue(f4.cancel())
        self.assertEquals(f4._state, CANCELLED_AND_NOTIFIED)

        self.assertFalse(f5.cancel())
        self.assertEquals(f5._state, FINISHED)

        self.assertFalse(f6.cancel())
        self.assertEquals(f6._state, FINISHED)

    def test_cancelled(self):
        self.assertFalse(PENDING_FUTURE.cancelled())
        self.assertFalse(RUNNING_FUTURE.cancelled())
        self.assertTrue(CANCELLED_FUTURE.cancelled())
        self.assertTrue(CANCELLED_AND_NOTIFIED_FUTURE.cancelled())
        self.assertFalse(EXCEPTION_FUTURE.cancelled())
        self.assertFalse(SUCCESSFUL_FUTURE.cancelled())

    def test_done(self):
        self.assertFalse(PENDING_FUTURE.done())
        self.assertFalse(RUNNING_FUTURE.done())
        self.assertTrue(CANCELLED_FUTURE.done())
        self.assertTrue(CANCELLED_AND_NOTIFIED_FUTURE.done())
        self.assertTrue(EXCEPTION_FUTURE.done())
        self.assertTrue(SUCCESSFUL_FUTURE.done())

    def test_running(self):
        self.assertFalse(PENDING_FUTURE.running())
        self.assertTrue(RUNNING_FUTURE.running())
        self.assertFalse(CANCELLED_FUTURE.running())
        self.assertFalse(CANCELLED_AND_NOTIFIED_FUTURE.running())
        self.assertFalse(EXCEPTION_FUTURE.running())
        self.assertFalse(SUCCESSFUL_FUTURE.running())

    def test_result_with_timeout(self):
        self.assertRaises(futures.TimeoutError,
                          PENDING_FUTURE.result, timeout=0)
        self.assertRaises(futures.TimeoutError,
                          RUNNING_FUTURE.result, timeout=0)
        self.assertRaises(futures.CancelledError,
                          CANCELLED_FUTURE.result, timeout=0)
        self.assertRaises(futures.CancelledError,
                          CANCELLED_AND_NOTIFIED_FUTURE.result, timeout=0)
        self.assertRaises(IOError, EXCEPTION_FUTURE.result, timeout=0)
        self.assertEqual(SUCCESSFUL_FUTURE.result(timeout=0), 42)

    def test_result_with_success(self):
        def notification():
            # Wait until the main thread is waiting for the result.
            time.sleep(1)
            with f1._condition:
                f1._state = FINISHED
                f1._result = 42
                f1._condition.notify_all()

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertEquals(f1.result(timeout=5), 42)

    def test_result_with_cancel(self):
        def notification():
            # Wait until the main thread is waiting for the result.
            time.sleep(1)
            with f1._condition:
                f1._state = CANCELLED
                f1._condition.notify_all()

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertRaises(futures.CancelledError, f1.result, timeout=5)

    def test_exception_with_timeout(self):
        self.assertRaises(futures.TimeoutError,
                          PENDING_FUTURE.exception, timeout=0)
        self.assertRaises(futures.TimeoutError,
                          RUNNING_FUTURE.exception, timeout=0)
        self.assertRaises(futures.CancelledError,
                          CANCELLED_FUTURE.exception, timeout=0)
        self.assertRaises(futures.CancelledError,
                          CANCELLED_AND_NOTIFIED_FUTURE.exception, timeout=0)
        self.assertTrue(isinstance(EXCEPTION_FUTURE.exception(timeout=0),
                                   IOError))
        self.assertEqual(SUCCESSFUL_FUTURE.exception(timeout=0), None)

    def test_exception_with_success(self):
        def notification():
            # Wait until the main thread is waiting for the exception.
            time.sleep(1)
            with f1._condition:
                f1._state = FINISHED
                f1._exception = IOError()
                f1._condition.notify_all()

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertTrue(isinstance(f1.exception(timeout=5), IOError))

class FutureListTests(unittest.TestCase):
    # FutureList.wait() is further tested by WaitsTest.
    # FutureList.cancel() is tested by CancelTests.
    def test_wait_RETURN_IMMEDIATELY(self):
        f = futures.FutureList(futures=None, event_sink=None)
        f.wait(return_when=futures.RETURN_IMMEDIATELY)

    def test_wait_timeout(self):
        f = futures.FutureList([PENDING_FUTURE],
                               futures._base.ThreadEventSink())

        for t in [futures.FIRST_COMPLETED,
                  futures.FIRST_EXCEPTION,
                  futures.ALL_COMPLETED]:
            f.wait(timeout=0.1, return_when=t)
            self.assertFalse(PENDING_FUTURE.done())

    def test_wait_all_done(self):
        f = futures.FutureList([CANCELLED_FUTURE,
                                CANCELLED_AND_NOTIFIED_FUTURE,
                                SUCCESSFUL_FUTURE,
                                EXCEPTION_FUTURE],
                               futures._base.ThreadEventSink())

        f.wait(return_when=futures.ALL_COMPLETED)

    def test_filters(self):
        fs = [PENDING_FUTURE,
              RUNNING_FUTURE,
              CANCELLED_FUTURE,
              CANCELLED_AND_NOTIFIED_FUTURE,
              EXCEPTION_FUTURE,
              SUCCESSFUL_FUTURE]
        f = futures.FutureList(fs, None)

        self.assertEqual(list(f.running_futures()), [RUNNING_FUTURE])
        self.assertEqual(list(f.cancelled_futures()),
                        [CANCELLED_FUTURE,
                         CANCELLED_AND_NOTIFIED_FUTURE])
        self.assertEqual(list(f.done_futures()),
                         [CANCELLED_FUTURE,
                          CANCELLED_AND_NOTIFIED_FUTURE,
                          EXCEPTION_FUTURE,
                          SUCCESSFUL_FUTURE])
        self.assertEqual(list(f.successful_futures()),
                         [SUCCESSFUL_FUTURE])
        self.assertEqual(list(f.exception_futures()),
                         [EXCEPTION_FUTURE])

    def test_has_running_futures(self):
        self.assertFalse(
                futures.FutureList([PENDING_FUTURE,
                                    CANCELLED_FUTURE,
                                    CANCELLED_AND_NOTIFIED_FUTURE,
                                    SUCCESSFUL_FUTURE,
                                    EXCEPTION_FUTURE],
                                   None).has_running_futures())
        self.assertTrue(
                futures.FutureList([RUNNING_FUTURE],
                                   None).has_running_futures())

    def test_has_cancelled_futures(self):
        self.assertFalse(
                futures.FutureList([PENDING_FUTURE,
                                    RUNNING_FUTURE,
                                    SUCCESSFUL_FUTURE,
                                    EXCEPTION_FUTURE],
                                   None).has_cancelled_futures())
        self.assertTrue(
                futures.FutureList([CANCELLED_FUTURE],
                                   None).has_cancelled_futures())

        self.assertTrue(
                futures.FutureList([CANCELLED_AND_NOTIFIED_FUTURE],
                                   None).has_cancelled_futures())

    def test_has_done_futures(self):
        self.assertFalse(
                futures.FutureList([PENDING_FUTURE,
                                    RUNNING_FUTURE],
                                   None).has_done_futures())
        self.assertTrue(
                futures.FutureList([CANCELLED_FUTURE],
                                   None).has_done_futures())

        self.assertTrue(
                futures.FutureList([CANCELLED_AND_NOTIFIED_FUTURE],
                                   None).has_done_futures())

        self.assertTrue(
                futures.FutureList([EXCEPTION_FUTURE],
                                   None).has_done_futures())

        self.assertTrue(
                futures.FutureList([SUCCESSFUL_FUTURE],
                                   None).has_done_futures())

    def test_has_successful_futures(self):
        self.assertFalse(
                futures.FutureList([PENDING_FUTURE,
                                    RUNNING_FUTURE,
                                    CANCELLED_FUTURE,
                                    CANCELLED_AND_NOTIFIED_FUTURE,
                                    EXCEPTION_FUTURE],
                                   None).has_successful_futures())

        self.assertTrue(
                futures.FutureList([SUCCESSFUL_FUTURE],
                                   None).has_successful_futures())

    def test_has_exception_futures(self):
        self.assertFalse(
                futures.FutureList([PENDING_FUTURE,
                                    RUNNING_FUTURE,
                                    CANCELLED_FUTURE,
                                    CANCELLED_AND_NOTIFIED_FUTURE,
                                    SUCCESSFUL_FUTURE],
                                   None).has_exception_futures())

        self.assertTrue(
                futures.FutureList([EXCEPTION_FUTURE],
                                   None).has_exception_futures())

    def test_get_item(self):
        fs = [PENDING_FUTURE, RUNNING_FUTURE, CANCELLED_FUTURE]
        f = futures.FutureList(fs, None)
        self.assertEqual(f[0], PENDING_FUTURE)
        self.assertEqual(f[1], RUNNING_FUTURE)
        self.assertEqual(f[2], CANCELLED_FUTURE)
        self.assertRaises(IndexError, f.__getitem__, 3)

    def test_len(self):
        f = futures.FutureList([PENDING_FUTURE,
                                RUNNING_FUTURE,
                                CANCELLED_FUTURE],
                               None)
        self.assertEqual(len(f), 3)

    def test_iter(self):
        fs = [PENDING_FUTURE, RUNNING_FUTURE, CANCELLED_FUTURE]
        f = futures.FutureList(fs, None)
        self.assertEqual(list(iter(f)), fs)

    def test_contains(self):
        f = futures.FutureList([PENDING_FUTURE,
                                RUNNING_FUTURE],
                               None)
        self.assertTrue(PENDING_FUTURE in f)
        self.assertTrue(RUNNING_FUTURE in f)
        self.assertFalse(CANCELLED_FUTURE in f)

    def test_repr(self):
        pending = create_future(state=PENDING)
        cancelled = create_future(state=CANCELLED)
        cancelled2 = create_future(state=CANCELLED_AND_NOTIFIED)
        running = create_future(state=RUNNING)
        finished = create_future(state=FINISHED)

        f = futures.FutureList(
                [PENDING_FUTURE] * 4 + [CANCELLED_FUTURE] * 2 +
                [CANCELLED_AND_NOTIFIED_FUTURE] +
                [RUNNING_FUTURE] * 2 +
                [SUCCESSFUL_FUTURE, EXCEPTION_FUTURE] * 3,
                None)

        self.assertEqual(repr(f),
                         '<FutureList #futures=15 '
                         '[#pending=4 #cancelled=3 #running=2 #finished=6]>')

def test_main():
    test.support.run_unittest(ProcessPoolCancelTests,
                              ThreadPoolCancelTests,
                              ProcessPoolExecutorTest,
                              ThreadPoolExecutorTest,
                              ProcessPoolWaitTests,
                              ThreadPoolWaitTests,
                              FutureTests,
                              FutureListTests,
                              ProcessPoolShutdownTest,
                              ThreadPoolShutdownTest)

if __name__ == "__main__":
    test_main()