"""Compare the speed of downloading URLs sequentially vs. using futures."""

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
        'http://www.bing.com/',
        'http://www.facebook.com/',
        'http://www.yahoo.com/',
        'http://www.youtube.com/',
        'http://www.blogger.com/']

def load_url(url):
    return urllib2.urlopen(url).read()

def download_urls_sequential(urls):
    url_to_content = {}
    for url in urls:
        try:
            url_to_content[url] = load_url(url)
        except:
            pass
    return url_to_content

def download_urls_with_executor(urls, executor):
    try:
        url_to_content = {}
        fs = executor.run_to_futures(
                (functools.partial(load_url, url) for url in urls))
        for future in fs.successful_futures():
            url = urls[future.index]
            url_to_content[url] = future.result()
        return url_to_content
    finally:
        executor.shutdown()

def main():
    for name, fn in [('sequential',
                      functools.partial(download_urls_sequential, URLS)),
                     ('threads',
                      functools.partial(download_urls_with_executor,
                                        URLS,
                                        futures.ThreadPoolExecutor(10)))]:
        print '%s: ' % name.ljust(12),
        start = time.time()
        url_map = fn()
        print '%.2f seconds (%d of %d downloaded)' % (time.time() - start,
                                                     len(url_map),
                                                     len(URLS))

main()
