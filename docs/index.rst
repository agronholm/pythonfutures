:mod:`futures` --- Asynchronous computation
===========================================

.. module:: futures
   :synopsis: Execute computations asynchronously using threads or processes. 

The :mod:`futures` module provides a high-level interface for asynchronously
executing functions and methods.

The asynchronous execution can be be performed by threads, using
:class:`ThreadPoolExecutor`, or seperate processes, using
:class:`ProcessPoolExecutor`. Both implement the same interface, which is
defined by the abstract :class:`Executor` class.

Executor Objects
----------------

:class:`Executor` is an abstract class that provides methods to execute calls
asynchronously. It should not be used directly, but through its two
subclasses: :class:`ThreadPoolExecutor` and :class:`ProcessPoolExecutor`.

.. method:: Executor.run_to_futures(calls, timeout=None, return_when=ALL_COMPLETED)

   Schedule the given calls for execution and return a :class:`FutureList`
   containing a :class:`Future` for each call. This method should always be
   called using keyword arguments, which are:

   *calls* must be a sequence of callables that take no arguments.

   *timeout* can be used to control the maximum number of seconds to wait before
   returning. If *timeout* is not specified or ``None`` then there is no limit
   to the wait time.

   *return_when* indicates when the method should return. It must be one of the
   following constants:

      +-----------------------------+----------------------------------------+
      | Constant                    | Description                            |
      +=============================+========================================+
      | :const:`FIRST_COMPLETED`    | The method will return when any call   |
      |                             | finishes.                              |
      +-----------------------------+----------------------------------------+
      | :const:`FIRST_EXCEPTION`    | The method will return when any call   |
      |                             | raises an exception or when all calls  |
      |                             | finish.                                |
      +-----------------------------+----------------------------------------+
      | :const:`ALL_COMPLETED`      | The method will return when all calls  |
      |                             | finish.                                |
      +-----------------------------+----------------------------------------+
      | :const:`RETURN_IMMEDIATELY` | The method will return immediately.    |
      +-----------------------------+----------------------------------------+

.. method:: Executor.run_to_results(calls, timeout=None)

   Schedule the given calls for execution and return an iterator over their
   results. The returned iterator raises a :exc:`TimeoutError` if
   :meth:`__next__()` is called and the result isn't available after
   *timeout* seconds from the original call to :meth:`run_to_results()`. If
   *timeout* is not specified or ``None`` then there is no limit to the wait
   time. If a call raises an exception then that exception will be raised when
   its value is retrieved from the iterator.

.. method:: Executor.map(func, *iterables, timeout=None)

   Equivalent to map(*func*, *\*iterables*) but executed asynchronously and
   possibly out-of-order. The returned iterator raises a :exc:`TimeoutError` if
   :meth:`__next__()` is called and the result isn't available after
   *timeout* seconds from the original call to :meth:`run_to_results()`. If
   *timeout* is not specified or ``None`` then there is no limit to the wait
   time. If a call raises an exception then that exception will be raised when
   its value is retrieved from the iterator.

.. method:: Executor.shutdown()

   Signal the executor that it should free any resources that it is using when
   the currently pending futures are done executing. Calls to
   :meth:`Executor.run_to_futures`, :meth:`Executor.run_to_results` and
   :meth:`Executor.map` made after shutdown will raise :exc:`RuntimeError`.

ThreadPoolExecutor Objects
--------------------------

The :class:`ThreadPoolExecutor` class is an :class:`Executor` subclass that uses
a pool of threads to execute calls asynchronously.

.. class:: ThreadPoolExecutor(max_threads)

   Executes calls asynchronously using at pool of at most *max_threads* threads.

.. _threadpoolexecutor-example:

ThreadPoolExecutor Example
^^^^^^^^^^^^^^^^^^^^^^^^^^
::

   import functools
   import urllib.request
   import futures
   
   URLS = ['http://www.foxnews.com/',
           'http://www.cnn.com/',
           'http://europe.wsj.com/',
           'http://www.bbc.co.uk/',
           'http://some-made-up-domain.com/']
   
   def load_url(url, timeout):
       return urllib.request.urlopen(url, timeout=timeout).read()
   
   with futures.ThreadPoolExecutor(50) as executor:
      future_list = executor.run_to_futures(
              [functools.partial(load_url, url, 30) for url in URLS])
   
   for url, future in zip(URLS, future_list):
       if future.exception() is not None:
           print('%r generated an exception: %s' % (url, future.exception()))
       else:
           print('%r page is %d bytes' % (url, len(future.result())))

ProcessPoolExecutor Objects
---------------------------

The :class:`ProcessPoolExecutor` class is an :class:`Executor` subclass that
uses a pool of processes to execute calls asynchronously.
:class:`ProcessPoolExecutor` uses the :mod:`multiprocessing` module, which
allows it to side-step the :term:`Global Interpreter Lock` but also means that
only picklable objects can be executed and returned.

.. class:: ProcessPoolExecutor(max_processes=None)

   Executes calls asynchronously using a pool of at most *max_processes*
   processes. If *max_processes* is ``None`` or not given then as many worker
   processes will be created as the machine has processors.

ProcessPoolExecutor Example
^^^^^^^^^^^^^^^^^^^^^^^^^^^
::

   PRIMES = [
       112272535095293,
       112582705942171,
       112272535095293,
       115280095190773,
       115797848077099,
       1099726899285419]

   def is_prime(n):
       if n % 2 == 0:
           return False

       sqrt_n = int(math.floor(math.sqrt(n)))
       for i in range(3, sqrt_n + 1, 2):
           if n % i == 0:
               return False
       return True

   with futures.ProcessPoolExecutor() as executor:
       for number, is_prime in zip(PRIMES, executor.map(is_prime, PRIMES)):
           print('%d is prime: %s' % (number, is_prime))

FutureList Objects
------------------

The :class:`FutureList` class is an immutable container for :class:`Future`
instances and should only be instantiated by :meth:`Executor.run_to_futures`.

.. method:: FutureList.wait(timeout=None, return_when=ALL_COMPLETED)

   Wait until the given conditions are met. This method should always be
   called using keyword arguments, which are:

   *timeout* can be used to control the maximum number of seconds to wait before
   returning. If *timeout* is not specified or ``None`` then there is no limit
   to the wait time.

   *return_when* indicates when the method should return. It must be one of the
   following constants:

      +-----------------------------+----------------------------------------+
      | Constant                    | Description                            |
      +=============================+========================================+
      | :const:`FIRST_COMPLETED`    | The method will return when any call   |
      |                             | finishes.                              |
      +-----------------------------+----------------------------------------+
      | :const:`FIRST_EXCEPTION`    | The method will return when any call   |
      |                             | raises an exception or when all calls  |
      |                             | finish.                                |
      +-----------------------------+----------------------------------------+
      | :const:`ALL_COMPLETED`      | The method will return when all calls  |
      |                             | finish.                                |
      +-----------------------------+----------------------------------------+
      | :const:`RETURN_IMMEDIATELY` | The method will return immediately.    |
      |                             | This option is only available for      |
      |                             | consistency with                       |
      |                             | :meth:`Executor.run_to_results` and is |
      |                             | not likely to be useful.               |
      +-----------------------------+----------------------------------------+

.. method:: FutureList.cancel(timeout=None)

   Cancel every :class:`Future` in the list and wait up to *timeout* seconds for
   them to be cancelled or, if any are already running, to finish. Raises a
   :exc:`TimeoutError` if the running calls do not complete before the timeout.
   If *timeout* is not specified or ``None`` then there is no limit to the wait
   time.

.. method:: FutureList.has_running_futures()

   Return `True` if any :class:`Future` in the list is currently executing.

.. method:: FutureList.has_cancelled_futures()

   Return `True` if any :class:`Future` in the list was successfully cancelled.

.. method:: FutureList.has_done_futures()

   Return `True` if any :class:`Future` in the list has completed or was
   successfully cancelled.

.. method:: FutureList.has_successful_futures()

   Return `True` if any :class:`Future` in the list has completed without raising
   an exception.

.. method:: FutureList.has_exception_futures()

   Return `True` if any :class:`Future` in the list completed by raising an
   exception.

.. method:: FutureList.cancelled_futures()

   Return an iterator over all :class:`Future` instances that were successfully
   cancelled.

.. method:: FutureList.done_futures()

   Return an iterator over all :class:`Future` instances that completed or
   were cancelled.

.. method:: FutureList.successful_futures()

   Return an iterator over all :class:`Future` instances that completed without
   raising an exception.

.. method:: FutureList.exception_futures()

   Return an iterator over all :class:`Future` instances that completed by
   raising an exception.

.. method:: FutureList.running_futures()

   Return an iterator over all :class:`Future` instances that are currently
   executing.

.. method:: FutureList.__len__()

   Return the number of futures in the :class:`FutureList`.

.. method:: FutureList.__getitem__(i)

   Return the ith :class:`Future` in the list. The order of the futures in the
   :class:`FutureList` matches the order of the class passed to
   :meth:`Executor.run_to_futures`

.. method:: FutureList.__contains__(future)

   Return `True` if *future* is in the :class:`FutureList`.

Future Objects
--------------

The :class:`Future` class encapulates the asynchronous execution of a function
or method call. :class:`Future` instances are created by
:meth:`Executor.run_to_futures` and bundled into a :class:`FutureList`.

.. method:: Future.cancel()

   Attempt to cancel the call. If the call is currently being executed then
   it cannot be cancelled and the method will return `False`, otherwise the call
   will be cancelled and the method will return `True`.

.. method:: Future.cancelled()

   Return `True` if the call was successfully cancelled.

.. method:: Future.done()

   Return `True` if the call was successfully cancelled or finished running.

.. method:: Future.result(timeout=None)

   Return the value returned by the call. If the call hasn't yet completed then
   this method will wait up to *timeout* seconds. If the call hasn't completed
   in *timeout* seconds then a :exc:`TimeoutError` will be raised. If *timeout*
   is not specified or ``None`` then there is no limit to the wait time.

   If the future is cancelled before completing then :exc:`CancelledError` will
   be raised.

   If the call raised then this method will raise the same exception.

.. method:: Future.exception(timeout=None)

   Return the exception raised by the call. If the call hasn't yet completed
   then this method will wait up to *timeout* seconds. If the call hasn't
   completed in *timeout* seconds then a :exc:`TimeoutError` will be raised.
   If *timeout* is not specified or ``None`` then there is no limit to the wait
   time.

   If the future is cancelled before completing then :exc:`CancelledError` will
   be raised.

   If the call completed without raising then ``None`` is returned.   

.. attribute:: Future.index

   int indicating the index of the future in its :class:`FutureList`.