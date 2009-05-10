import test.support
from test.support import verbose

import unittest
import threading
import time
import multiprocessing

import futures
import futures._base
from futures._base import (
    PENDING, RUNNING, CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED, Future)

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

class Call(object):
    CALL_LOCKS = {}
    def __init__(self, manual_finish=False):
        called_event = multiprocessing.Event()
        can_finish = multiprocessing.Event()

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
        return 42

    def __del__(self):
        del self.CALL_LOCKS[self._called_event_id]
        del self.CALL_LOCKS[self._can_finish_event_id]

class ExceptionCall(Call):
    def __call__(self):
        assert not self._called_event.is_set(), 'already called'

        self._called_event.set()
        self._can_finish.wait()
        raise ZeroDivisionError()

class ShutdownTest(unittest.TestCase):
    def test_run_after_shutdown(self):
        call1 = Call()
        self.executor.shutdown()
        self.assertRaises(RuntimeError,
                          self.executor.run_to_futures,
                          [call1])

    def _start_some_futures(self):
        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        call3 = Call(manual_finish=True)

        self.executor.run_to_futures([call1, call2, call3],
                                     return_when=futures.RETURN_IMMEDIATELY)

        call1.wait_on_called()
        call2.wait_on_called()
        call3.wait_on_called()

        call1.set_can()
        call2.set_can()
        call3.set_can()

class ThreadPoolShutdownTest(ShutdownTest):
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

class ProcessPoolShutdownTest(ShutdownTest):
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

class WaitsTest(unittest.TestCase):
    def test(self):
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

    def test_wait_for_individual_cancel(self):
        def end_call():
            time.sleep(1)
            f2.cancel()
            call1.set_can()

        call1 = Call(manual_finish=True)
        call2 = Call()

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

    def test_wait_with_already_cancelled_futures(self):
        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        fs = self.executor.run_to_futures(
                [call1, call2, call3, call4],
                return_when=futures.RETURN_IMMEDIATELY)
        f1, f2, f3, f4 = fs

        call1.wait_on_called()
        self.assertTrue(f2.cancel())
        self.assertTrue(f3.cancel())
        call1.set_can()
        time.sleep(0.1)

        fs.wait(return_when=futures.ALL_COMPLETED)

    def test_cancel_all(self):
        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

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

class FutureTests(unittest.TestCase):
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
            time.sleep(0.1)
            with f1._condition:
                f1._state = FINISHED
                f1._result = 42
                f1._condition.notify_all()

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertEquals(f1.result(timeout=1), 42)

    def test_result_with_cancel(self):
        def notification():
            time.sleep(0.1)
            with f1._condition:
                f1._state = CANCELLED
                f1._condition.notify_all()

        f1 = create_future(state=PENDING)
        t = threading.Thread(target=notification)
        t.start()

        self.assertRaises(futures.CancelledError, f1.result, timeout=1)

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

class FutureListTests(unittest.TestCase):
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
                              ProcessPoolWaitTests,
                              ThreadPoolWaitTests,
                              FutureTests,
                              FutureListTests,
                              ProcessPoolShutdownTest,
                              ThreadPoolShutdownTest)

if __name__ == "__main__":
    test_main()