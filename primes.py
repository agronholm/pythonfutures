import futures
import math
import time

PRIMES = [
    112272535095293,
    112582705942171,
    112272535095293,
    115280095190773,
    115797848077099]

def is_prime(n):
    n = abs(n)
    i = 2
    while i <= math.sqrt(n):
        if n % i == 0:
            return False
        i += 1
    return True

def sequential():
    return list(map(is_prime, PRIMES))

def with_process_pool_executor():
    executor = futures.ProcessPoolExecutor()
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
        start = time.time()
        fn()
        print('%s: %.2f seconds' % (name.ljust(10), time.time() - start))

main()