import test.support
from test.support import verbose

import unittest
import threading
import time
import multiprocessing

import futures

class Call(object):
    def __init__(self, manual_finish=False):
        self._called_event = threading.Event()

        self._can_finished = threading.Event()
        if not manual_finish:
            self._can_finished.set()

    def wait_on_called(self):
        self._called_event.wait()

    def set_can(self):
        self._can_finished.set()

    def called(self):
        return self._called_event.is_set()

    def __call__(self):
        if self._called_event.is_set(): print('called twice')

        self._called_event.set()
        self._can_finished.wait()
        return 42

class ExceptionCall(Call):
    def __call__(self):
        assert not self._called_event.is_set(), 'already called'

        self._called_event.set()
        self._can_finished.wait()
        raise ZeroDivisionError()

class FutureStub(object):
    def __init__(self, cancelled, done, exception=None):
        self._cancelled = cancelled
        self._done = done
        self._exception = exception

    def cancelled(self):
        return self._cancelled

    def done(self):
        return self._done

    def exception(self):
        return self._exception

class ShutdownTest(unittest.TestCase):
    def test_run_after_shutdown(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=1)

        call1 = Call()
        self.executor.shutdown()
        self.assertRaises(RuntimeError,
                          self.executor.run,
                          [call1])

    def test_threads_terminate(self):
        self.executor = futures.ThreadPoolExecutor(max_threads=5)

        call1 = Call(manual_finish=True)
        call2 = Call(manual_finish=True)
        call3 = Call(manual_finish=True)

        self.executor.run([call1, call2, call3],
                          run_until=futures.RETURN_IMMEDIATELY)

        call1.wait_on_called()
        call2.wait_on_called()
        call3.wait_on_called()

        call1.set_can()
        call2.set_can()
        call3.set_can()

        self.assertEqual(len(self.executor._threads), 3)
        self.executor.shutdown()
        for t in self.executor._threads:
            t.join()
            

class WaitsTest(unittest.TestCase):
    def test(self):
        def aaa():
            fs.wait(run_until=futures.ALL_COMPLETED)
            self.assertTrue(f1.done())
            self.assertTrue(f2.done())
            self.assertTrue(f3.done())
            self.assertTrue(f4.done())

        def bbb():
            fs.wait(run_until=futures.FIRST_COMPLETED)
            self.assertTrue(f1.done())
            self.assertFalse(f2.done())
            self.assertFalse(f3.done())
            self.assertFalse(f4.done())

        def ccc():
            fs.wait(run_until=futures.FIRST_EXCEPTION)
            self.assertTrue(f1.done())
            self.assertTrue(f2.done())
            self.assertFalse(f3.done())
            self.assertFalse(f4.done())

        call1 = Call(manual_finish=True)
        call2 = ExceptionCall(manual_finish=True)
        call3 = Call(manual_finish=True)
        call4 = Call()

        fs = self.executor.run([call1, call2, call3, call4],
                          run_until=futures.RETURN_IMMEDIATELY)
        f1, f2, f3, f4 = fs

        threads = []
        for call in [aaa, bbb, ccc] * 3:
            t = threading.Thread(target=call)
            t.start()
            threads.append(t)

        time.sleep(1)
        call1.set_can()
        time.sleep(1)
        call2.set_can()        
        time.sleep(1)
        call3.set_can()
        time.sleep(1)
        call4.set_can()

        for t in threads:
            t.join()
        self.executor.shutdown()

class ThreadPoolWaitTests(WaitsTest):
    executor = futures.ThreadPoolExecutor(max_threads=1)

class ProcessPoolWaitTests(WaitsTest):
    executor = futures.ProcessPoolExecutor(max_processes=1)

class CancelTests(unittest.TestCase):
    def test_cancel_states(self):
        executor = futures.ThreadPoolExecutor(max_threads=1)

        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        fs = executor.run([call1, call2, call3, call4],
                          run_until=futures.RETURN_IMMEDIATELY)
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
        fs.wait(run_until=futures.ALL_COMPLETED)
        self.assertEqual(f1.result(), 42)
        self.assertRaises(futures.CancelledException, f2.result)
        self.assertRaises(futures.CancelledException, f2.exception)
        self.assertEqual(f3.result(), 42)
        self.assertRaises(futures.CancelledException, f4.result)
        self.assertRaises(futures.CancelledException, f4.exception)

        self.assertEqual(call2.called(), False)
        self.assertEqual(call4.called(), False)
        executor.shutdown()

    def test_wait_for_individual_cancel(self):
        def end_call():
            time.sleep(1)
            f2.cancel()
            call1.set_can()

        executor = futures.ThreadPoolExecutor(max_threads=1)

        call1 = Call(manual_finish=True)
        call2 = Call()

        fs = executor.run([call1, call2], run_until=futures.RETURN_IMMEDIATELY)
        f1, f2 = fs

        call1.wait_on_called()
        t = threading.Thread(target=end_call)
        t.start()
        self.assertRaises(futures.CancelledException, f2.result)
        self.assertRaises(futures.CancelledException, f2.exception)
        t.join()
        executor.shutdown()

    def test_cancel_all(self):
        executor = futures.ThreadPoolExecutor(max_threads=1)

        call1 = Call(manual_finish=True)
        call2 = Call()
        call3 = Call()
        call4 = Call()

        fs = executor.run([call1, call2, call3, call4],
                          run_until=futures.RETURN_IMMEDIATELY)
        f1, f2, f3, f4 = fs

        call1.wait_on_called()
        self.assertRaises(futures.TimeoutException, fs.cancel, timeout=0)
        call1.set_can()
        fs.cancel()

        self.assertFalse(f1.cancelled())
        self.assertTrue(f2.cancelled())
        self.assertTrue(f3.cancelled())
        self.assertTrue(f4.cancelled())
        executor.shutdown()

    def test_cancel_repr(self):
        executor = futures.ThreadPoolExecutor(max_threads=1)

        call1 = Call(manual_finish=True)
        call2 = Call()

        fs = executor.run([call1, call2], run_until=futures.RETURN_IMMEDIATELY)
        f1, f2 = fs

        call1.wait_on_called()
        call1.set_can()
        f2.cancel()
        self.assertEqual(repr(f2), '<Future state=cancelled>')
        executor.shutdown()

class FutureListTests(unittest.TestCase):
    def test_cancel_states(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=True, exception=IOError())
        f4 = FutureStub(cancelled=True, done=True)

        fs = [f1, f2, f3, f4]
        f = futures.FutureList(fs, None)

        self.assertEqual(f.running_futures(), [f1])
        self.assertEqual(f.cancelled_futures(), [f4])
        self.assertEqual(f.done_futures(), [f2, f3, f4])
        self.assertEqual(f.successful_futures(), [f2])
        self.assertEqual(f.exception_futures(), [f3])

    def test_has_running_futures(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)

        self.assertTrue(
                futures.FutureList([f1], None).has_running_futures())
        self.assertFalse(
                futures.FutureList([f2], None).has_running_futures())

    def test_has_cancelled_futures(self):
        f1 = FutureStub(cancelled=True, done=True)
        f2 = FutureStub(cancelled=False, done=True)

        self.assertTrue(
                futures.FutureList([f1], None).has_cancelled_futures())
        self.assertFalse(
                futures.FutureList([f2], None).has_cancelled_futures())

    def test_has_done_futures(self):
        f1 = FutureStub(cancelled=True, done=True)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=False)

        self.assertTrue(
                futures.FutureList([f1], None).has_done_futures())
        self.assertTrue(
                futures.FutureList([f2], None).has_done_futures())
        self.assertFalse(
                futures.FutureList([f3], None).has_done_futures())

    def test_has_successful_futures(self):
        f1 = FutureStub(cancelled=False, done=True)
        f2 = FutureStub(cancelled=False, done=True, exception=IOError())
        f3 = FutureStub(cancelled=False, done=False)
        f4 = FutureStub(cancelled=True, done=True)

        self.assertTrue(
                futures.FutureList([f1], None).has_successful_futures())
        self.assertFalse(
                futures.FutureList([f2], None).has_successful_futures())
        self.assertFalse(
                futures.FutureList([f3], None).has_successful_futures())
        self.assertFalse(
                futures.FutureList([f4], None).has_successful_futures())

    def test_has_exception_futures(self):
        f1 = FutureStub(cancelled=False, done=True)
        f2 = FutureStub(cancelled=False, done=True, exception=IOError())
        f3 = FutureStub(cancelled=False, done=False)
        f4 = FutureStub(cancelled=True, done=True)

        self.assertFalse(
                futures.FutureList([f1], None).has_exception_futures())
        self.assertTrue(
                futures.FutureList([f2], None).has_exception_futures())
        self.assertFalse(
                futures.FutureList([f3], None).has_exception_futures())
        self.assertFalse(
                futures.FutureList([f4], None).has_exception_futures())

    def test_get_item(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=True)

        fs = [f1, f2, f3]
        f = futures.FutureList(fs, None)
        self.assertEqual(f[0], f1)
        self.assertEqual(f[1], f2)
        self.assertEqual(f[2], f3)
        self.assertRaises(IndexError, f.__getitem__, 3)

    def test_len(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=True)

        f = futures.FutureList([f1, f2, f3], None)
        self.assertEqual(len(f), 3)

    def test_iter(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=True)

        fs = [f1, f2, f3]
        f = futures.FutureList(fs, None)
        self.assertEqual(list(iter(f)), fs)

    def test_contains(self):
        f1 = FutureStub(cancelled=False, done=False)
        f2 = FutureStub(cancelled=False, done=True)
        f3 = FutureStub(cancelled=False, done=True)

        f = futures.FutureList([f1, f2], None)
        self.assertTrue(f1 in f)
        self.assertTrue(f2 in f)
        self.assertFalse(f3 in f)

    def test_repr(self):
        running = FutureStub(cancelled=False, done=False)
        result = FutureStub(cancelled=False, done=True)
        exception = FutureStub(cancelled=False, done=True, exception=IOError())
        cancelled = FutureStub(cancelled=True, done=True)

        f = futures.FutureList(
                [running] * 4 + [result] * 3 + [exception] * 2 + [cancelled],
                None)

        self.assertEqual(repr(f),
                         '<FutureList #futures=10 '
                         '[#success=3 #exception=2 #cancelled=1]>')
def test_main():
    test.support.run_unittest(CancelTests,
#                              ProcessPoolWaitTests,
                              ThreadPoolWaitTests,
                              FutureListTests,
                              ShutdownTest)

if __name__ == "__main__":
    test_main()