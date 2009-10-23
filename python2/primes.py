import futures
import math
import time

PRIMES = [
    112272535095293,
    112582705942171,
    112272535095293,
    115280095190773,
    115797848077099,
    117450548693743,
    993960000099397]

def is_prime(n):
    if n % 2 == 0:
        return False

    sqrt_n = int(math.floor(math.sqrt(n)))
    for i in range(3, sqrt_n + 1, 2):
        if n % i == 0:
            return False
    return True

def sequential():
    return list(map(is_prime, PRIMES))

def with_process_pool_executor():
    executor = futures.ProcessPoolExecutor(10)
    try:
        return list(executor.map(is_prime, PRIMES))
    finally:
        executor.shutdown()

def with_thread_pool_executor():
    executor = futures.ThreadPoolExecutor(10)
    try:
        return list(executor.map(is_prime, PRIMES))
    finally:
        executor.shutdown()

def main():
    for name, fn in [('sequential', sequential),
                     ('processes', with_process_pool_executor),
                     ('threads', with_thread_pool_executor)]:
        print '%s: ' % name.ljust(12),

        start = time.time()
        if fn() != [True] * len(PRIMES):
            print 'failed'
        else:
            print '%.2f seconds' % (time.time() - start)

main()