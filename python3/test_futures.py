import test.support

import unittest
import threading
import time
import multiprocessing

import futures
import futures._base
from futures._base import (
    PENDING, RUNNING, CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED, Future, wait)
import futures.process

def create_future(state=PENDING, exception=None, result=None):
    f = Future()
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

def mul(x, y):
    return x * y

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
        self.executor.shutdown()
        self.assertRaises(RuntimeError,
                          self.executor.submit,
                          pow, 2, 5)


    def _start_some_futures(self):
        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        call3 = Call(manual_finish=True)

        try:
            self.executor.submit(call1)
            self.executor.submit(call2)
            self.executor.submit(call3)

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
        self.executor.shutdown(wait=True)

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

    def test_del_shutdown(self):
        executor = futures.ThreadPoolExecutor(max_threads=5)
        executor.map(abs, range(-5, 5))
        threads = executor._threads
        del executor

        for t in threads:
            t.join()

class ProcessPoolShutdownTest(ExecutorShutdownTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=5)

    def tearDown(self):
        self.executor.shutdown(wait=True)

    def test_processes_terminate(self):
        self._start_some_futures()
        self.assertEqual(len(self.executor._processes), 5)
        self.executor.shutdown()

        self.executor._queue_management_thread.join()
        for p in self.executor._processes:
            p.join()

    def test_context_manager_shutdown(self):
        with futures.ProcessPoolExecutor(max_processes=5) as e:
            executor = e
            self.assertEqual(list(e.map(abs, range(-5, 5))),
                             [5, 4, 3, 2, 1, 0, 1, 2, 3, 4])

        executor._queue_management_thread.join()
        for p in self.executor._processes:
            p.join()

    def test_del_shutdown(self):
        executor = futures.ProcessPoolExecutor(max_processes=5)
        list(executor.map(abs, range(-5, 5)))
        queue_management_thread = executor._queue_management_thread
        processes = executor._processes
        del executor

        queue_management_thread.join()
        for p in processes:
            p.join()

class WaitTests(unittest.TestCase):
    def test_first_completed(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [CANCELLED_FUTURE, future1, future2],
                     return_when=futures.FIRST_COMPLETED)

            self.assertEquals(set([future1]), finished)
            self.assertEquals(set([CANCELLED_FUTURE, future2]), pending)
        finally:
            call2.set_can()
            call1.close()
            call2.close()

    def test_first_completed_one_already_completed(self):
        call1 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)

            finished, pending = futures.wait(
                     [SUCCESSFUL_FUTURE, future1],
                     return_when=futures.FIRST_COMPLETED)

            self.assertEquals(set([SUCCESSFUL_FUTURE]), finished)
            self.assertEquals(set([future1]), pending)
        finally:
            call1.set_can()
            call1.close()

    def test_first_exception(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()
            call2.set_can()

        call1 = Call(manual_finish=True)
        call2 = ExceptionCall(manual_finish=True)
        call3 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)
            future3 = self.executor.submit(call3)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [future1, future2, future3],
                    return_when=futures.FIRST_EXCEPTION)

            self.assertEquals(set([future1, future2]), finished)
            self.assertEquals(set([future3]), pending)


        finally:
            call3.set_can()
            call1.close()
            call2.close()
            call3.close()

    def test_first_exception_some_already_complete(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()

        call1 = ExceptionCall(manual_finish=True)
        call2 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [SUCCESSFUL_FUTURE,
                     CANCELLED_FUTURE,
                     CANCELLED_AND_NOTIFIED_FUTURE,
                     future1, future2],
                    return_when=futures.FIRST_EXCEPTION)

            self.assertEquals(set([SUCCESSFUL_FUTURE,
                                   CANCELLED_AND_NOTIFIED_FUTURE,
                                   future1]), finished)
            self.assertEquals(set([CANCELLED_FUTURE, future2]), pending)


        finally:
            call2.set_can()
            call1.close()
            call2.close()

    def test_first_exception_one_already_failed(self):
        call1 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)

            finished, pending = futures.wait(
                     [EXCEPTION_FUTURE, future1],
                     return_when=futures.FIRST_EXCEPTION)

            self.assertEquals(set([EXCEPTION_FUTURE]), finished)
            self.assertEquals(set([future1]), pending)
        finally:
            call1.set_can()
            call1.close()

    def test_all_completed(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()
            call2.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [future1, future2],
                    return_when=futures.ALL_COMPLETED)

            self.assertEquals(set([future1, future2]), finished)
            self.assertEquals(set(), pending)


        finally:
            call1.close()
            call2.close()

    def test_all_completed_some_already_completed(self):
        def wait_test():
            while not future1._waiters:
                pass

            future4.cancel()
            call1.set_can()
            call2.set_can()
            call3.set_can()

        self.assertLessEqual(
                futures.process.EXTRA_QUEUED_CALLS,
                1,
               'this test assumes that future4 will be cancelled before it is '
               'queued to run - which might not be the case if '
               'ProcessPoolExecutor is too aggresive in scheduling futures') 
        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        call3 = Call(manual_finish=True)
        call4 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)
            future3 = self.executor.submit(call3)
            future4 = self.executor.submit(call4)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [SUCCESSFUL_FUTURE,
                     CANCELLED_AND_NOTIFIED_FUTURE,
                     future1, future2, future3, future4],
                    return_when=futures.ALL_COMPLETED)

            self.assertEquals(set([SUCCESSFUL_FUTURE,
                                   CANCELLED_AND_NOTIFIED_FUTURE,
                                   future1, future2, future3, future4]),
                              finished)
            self.assertEquals(set(), pending)
        finally:
            call1.close()
            call2.close()
            call3.close()
            call4.close()

    def test_timeout(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)

            t = threading.Thread(target=wait_test)
            t.start()
            finished, pending = futures.wait(
                    [CANCELLED_AND_NOTIFIED_FUTURE,
                     EXCEPTION_FUTURE,
                     SUCCESSFUL_FUTURE,
                     future1, future2],
                    timeout=1,
                    return_when=futures.ALL_COMPLETED)

            self.assertEquals(set([CANCELLED_AND_NOTIFIED_FUTURE,
                                   EXCEPTION_FUTURE,
                                   SUCCESSFUL_FUTURE,
                                   future1]), finished)
            self.assertEquals(set([future2]), pending)


        finally:
            call2.set_can()
            call1.close()
            call2.close()


class ThreadPoolWaitTests(WaitTests):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class ProcessPoolWaitTests(WaitTests):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class AsCompletedTests(unittest.TestCase):
    # TODO(brian@sweetapp.com): Should have a test with a non-zero timeout.
    def test_no_timeout(self):
        def wait_test():
            while not future1._waiters:
                pass
            call1.set_can()
            call2.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            future2 = self.executor.submit(call2)

            t = threading.Thread(target=wait_test)
            t.start()
            completed = set(futures.as_completed(
                    [CANCELLED_AND_NOTIFIED_FUTURE,
                     EXCEPTION_FUTURE,
                     SUCCESSFUL_FUTURE,
                     future1, future2]))
            self.assertEquals(set(
                    [CANCELLED_AND_NOTIFIED_FUTURE,
                     EXCEPTION_FUTURE,
                     SUCCESSFUL_FUTURE,
                     future1, future2]),
                    completed)
        finally:
            call2.set_can()
            call1.close()
            call2.close()

    def test_zero_timeout(self):
        call1 = Call(manual_finish=True)
        try:
            future1 = self.executor.submit(call1)
            completed_futures = set()
            try:
                for future in futures.as_completed(
                        [CANCELLED_AND_NOTIFIED_FUTURE,
                         EXCEPTION_FUTURE,
                         SUCCESSFUL_FUTURE,
                         future1],
                        timeout=0):
                    completed_futures.add(future)
            except futures.TimeoutError:
                pass 

            self.assertEquals(set([CANCELLED_AND_NOTIFIED_FUTURE,
                                   EXCEPTION_FUTURE,
                                   SUCCESSFUL_FUTURE]),
                              completed_futures)
        finally:
            call1.set_can()

class ThreadPoolAsCompletedTests(AsCompletedTests):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class ProcessPoolAsCompletedTests(AsCompletedTests):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class ExecutorTest(unittest.TestCase):
    # Executor.shutdown() and context manager usage is tested by
    # ExecutorShutdownTest.
    def test_submit(self):
        future = self.executor.submit(pow, 2, 8)
        self.assertEquals(256, future.result())

    def test_submit_keyword(self):
        future = self.executor.submit(mul, 2, y=8)
        self.assertEquals(16, future.result())
    
    def test_map(self):
        self.assertEqual(
                list(self.executor.map(pow, range(10), range(10))),
                list(map(pow, range(10), range(10))))

    def test_map_exception(self):
        i = self.executor.map(divmod, [1, 1, 1, 1], [2, 3, 0, 5])
        self.assertEqual(i.__next__(), (0, 1))
        self.assertEqual(i.__next__(), (0, 1))
        self.assertRaises(ZeroDivisionError, i.__next__)

    def test_map_timeout(self):
        results = []
        try:
            for i in self.executor.map(time.sleep, [0, 0.1, 1], timeout=1):
                results.append(i)
        except futures.TimeoutError:
            pass
        else:
            self.fail('expected TimeoutError')
        self.assertEquals([None, None], results)

class ThreadPoolExecutorTest(ExecutorTest):
    def setUp(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class ProcessPoolExecutorTest(ExecutorTest):
    def setUp(self):
        self.executor = futures.ProcessPoolExecutor(max_processes=1)

    def tearDown(self):
        self.executor.shutdown(wait=True)

class FutureTests(unittest.TestCase):
    def test_repr(self):
        self.assertRegexpMatches(repr(PENDING_FUTURE),
                                 '<Future at 0x[0-9a-f]+ state=pending>')
        self.assertRegexpMatches(repr(RUNNING_FUTURE),
                                 '<Future at 0x[0-9a-f]+ state=running>')
        self.assertRegexpMatches(repr(CANCELLED_FUTURE),
                                 '<Future at 0x[0-9a-f]+ state=cancelled>')
        self.assertRegexpMatches(repr(CANCELLED_AND_NOTIFIED_FUTURE),
                                 '<Future at 0x[0-9a-f]+ state=cancelled>')
        self.assertRegexpMatches(
                repr(EXCEPTION_FUTURE),
                '<Future at 0x[0-9a-f]+ state=finished raised IOError>')
        self.assertRegexpMatches(
                repr(SUCCESSFUL_FUTURE),
                '<Future at 0x[0-9a-f]+ state=finished returned int>')


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
        # TODO(brian@sweetapp.com): This test is timing dependant.
        def notification():
            # Wait until the main thread is waiting for the result.
            time.sleep(1)
            f1._set_result(42)

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertEquals(f1.result(timeout=5), 42)

    def test_result_with_cancel(self):
        # TODO(brian@sweetapp.com): This test is timing dependant.
        def notification():
            # Wait until the main thread is waiting for the result.
            time.sleep(1)
            f1.cancel()

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

def test_main():
    test.support.run_unittest(ProcessPoolExecutorTest,
                              ThreadPoolExecutorTest,
                              ProcessPoolWaitTests,
                              ThreadPoolWaitTests,
                              ProcessPoolAsCompletedTests,
                              ThreadPoolAsCompletedTests,
                              FutureTests,
                              ProcessPoolShutdownTest,
                              ThreadPoolShutdownTest)

if __name__ == "__main__":
    test_main()
