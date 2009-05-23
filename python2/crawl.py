import datetime
import functools
import futures.thread
import time
import timeit
import urllib2

URLS = ['http://www.google.com/',
        'http://www.apple.com/',
        'http://www.ibm.com',
        'http://www.thisurlprobablydoesnotexist.com',
        'http://www.slashdot.org/',
        'http://www.python.org/',
        'http://www.sweetapp.com/'] * 5

def load_url(url, timeout):
    return urllib2.urlopen(url, timeout=timeout).read()

def download_urls_sequential(urls, timeout=60):
    url_to_content = {}
    for url in urls:
        try:
            url_to_content[url] = load_url(url, timeout=timeout)
        except:
            pass
    return url_to_content

def download_urls_with_executor(urls, executor, timeout=60):
    try:
        url_to_content = {}
        fs = executor.run_to_futures(
                (functools.partial(load_url, url, timeout) for url in urls),
                timeout=timeout)
        for future in fs.successful_futures():
            url = urls[future.index]
            url_to_content[url] = future.result()
        return url_to_content
    finally:
        executor.shutdown()

def main():
    for name, fn in [('sequential',
                      functools.partial(download_urls_sequential, URLS)),
                     ('processes',
                      functools.partial(download_urls_with_executor,
                                        URLS,
                                        futures.ProcessPoolExecutor(10))),
                     ('threads',
                      functools.partial(download_urls_with_executor,
                                        URLS,
                                        futures.ThreadPoolExecutor(10)))]:
        print '%s: ' % name.ljust(12),
        start = time.time()
        fn()
        print '%.2f seconds' % (time.time() - start)

main()
