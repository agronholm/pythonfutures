import datetime
import functools
import futures.thread
import time
import timeit
import urllib.request

URLS = ['http://www.google.com/',
        'http://www.apple.com/',
        'http://www.ibm.com',
        'http://www.thisurlprobablydoesnotexist.com',
        'http://www.slashdot.org/',
        'http://www.python.org/',
        'http://www.sweetapp.com/'] * 1000

def load_url(url, timeout):
    return urllib.request.urlopen(url, timeout=timeout).read()

def download_urls(urls, timeout=60):
    url_to_content = {}
    for url in urls:
        try:
            url_to_content[url] = load_url(url, timeout=timeout)
        except:
            pass
    return url_to_content

executor = futures.ProcessPoolExecutor(100)
def download_urls_with_futures(urls, timeout=60):
    url_to_content = {}
    fs = executor.run(
            (functools.partial(load_url, url, timeout) for url in urls),
            timeout=timeout)
    for url, future in zip(urls, fs.successful_futures()):
        url_to_content[url] = future.result()
    return url_to_content

print(download_urls_with_futures(URLS))
