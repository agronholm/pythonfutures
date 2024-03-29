3.4.0
=====

- Backported bpo-21423: Add an initializer argument to {Process,Thread}PoolExecutor
  (only ThreadPoolExecutor for now; PR by Fahrzin Hemmati)


3.3.0
=====

- Backported bpo-24882: Let ThreadPoolExecutor reuse idle threads before creating new thread


3.2.0
=====

- The ThreadPoolExecutor class constructor now accepts an optional ``thread_name_prefix``
  argument to make it possible to customize the names of the threads created by the pool.
  Upstream contribution by Gregory P. Smith in https://bugs.python.org/issue27664.
- Backported fixes from upstream (thanks Lisandro Dalcin):

 - python/cpython#1560
 - python/cpython#3270
 - python/cpython#3830


3.1.1
=====

- Backported sanity checks for the ``max_workers`` constructor argument for
  ThreadPoolExecutor and ProcessPoolExecutor
- Set the default value of ``max_workers`` in ThreadPoolExecutor to ``None``,
  as in upstream code (computes the thread pool size based on the number of
  CPUs)
- Added support for old-style exception objects
- Switched to the PSF license


3.1.0
=====

- (Failed release)


3.0.5
=====

- Fixed OverflowError with ProcessPoolExecutor on Windows (regression
  introduced in 3.0.4)


3.0.4
=====

- Fixed inability to forcibly terminate the process if there are pending workers


3.0.3
=====

- Fixed AttributeErrors on exit on Python 2.x


3.0.2
=====

- Made multiprocessing optional again on implementations other than just Jython


3.0.1
=====

- Made Executor.map() non-greedy


3.0.0
=====

- Dropped Python 2.5 and 3.1 support
- Removed the deprecated "futures" top level package
- Applied patch for issue 11777 (Executor.map does not submit futures until
  iter.next() is called)
- Applied patch for issue 15015 (accessing a non-existing attribute)
- Applied patch for issue 16284 (memory leak)
- Applied patch for issue 20367 (behavior of concurrent.futures.as_completed()
  for duplicate arguments)

2.2.0
=====

- Added the set_exception_info() and exception_info() methods to Future
  to enable extraction of tracebacks on Python 2.x
- Added support for Future.set_exception_info() to ThreadPoolExecutor


2.1.6
=====

- Fixed a problem with files missing from the source distribution


2.1.5
=====

- Fixed Jython compatibility
- Added metadata for wheel support


2.1.4
=====

- Ported the library again from Python 3.2.5 to get the latest bug fixes


2.1.3
=====

- Fixed race condition in wait(return_when=ALL_COMPLETED)
  (http://bugs.python.org/issue14406) -- thanks Ralf Schmitt
- Added missing setUp() methods to several test classes


2.1.2
=====

- Fixed installation problem on Python 3.1


2.1.1
=====

- Fixed missing 'concurrent' package declaration in setup.py


2.1
===

- Moved the code from the 'futures' package to 'concurrent.futures' to provide
  a drop in backport that matches the code in Python 3.2 standard library
- Deprecated the old 'futures' package


2.0
===

- Changed implementation to match PEP 3148


1.0
===

- Initial release
