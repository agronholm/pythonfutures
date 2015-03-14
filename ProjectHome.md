A Java-style futures package for Python

This package is described in [PEP-3148](http://www.python.org/dev/peps/pep-3148/) and is included in Python 3.2.

See the [Python documentation](http://docs.python.org/dev/library/concurrent.futures.html) for a full description.

[Python 2.6+ Releases](http://pypi.python.org/pypi/futures)

[Python 3.0 and 3.1 Releases](http://pypi.python.org/pypi/futures3)

# Example (Python 2.6) #
```
import futures
import urllib2

URLS = ['http://www.foxnews.com/',
        'http://www.cnn.com/',
        'http://europe.wsj.com/',
        'http://www.bbc.co.uk/',
        'http://some-made-up-domain.com/']

def load_url(url, timeout):
    return urllib2.urlopen(url, timeout=timeout).read()

with futures.ThreadPoolExecutor(max_workers=5) as executor:
    future_to_url = dict((executor.submit(load_url, url, 60), url)
                         for url in URLS)

    for future in futures.as_completed(future_to_url):
        url = future_to_url[future]
        if future.exception() is not None:
            print '%r generated an exception: %s' % (url,
                                                     future.exception())
        else:
            print '%r page is %d bytes' % (url, len(future.result()))
```