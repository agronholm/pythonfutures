import multiprocessing
import queue

def _process_worker(q):
    while True:
        try:
            something = q.get(block=True, timeout=0.1)
        except queue.Empty:
            return
        else:
            print('Grabbed item from queue:', something)


def _make_some_processes(q):
    processes = []
    for _ in range(10):
        p = multiprocessing.Process(target=_process_worker, args=(q,))
        p.start()
        processes.append(p)
    return processes

def _do(i):
    print('Run:', i)
    q = multiprocessing.Queue()
    print('Created queue')
    for j in range(30):
        q.put(i*30+j)
    processes = _make_some_processes(q)
    print('Created processes')

    while not q.empty():
        pass
    print('Q is empty')

    # Without the two following commented lines, the output on Mac OS 10.5 (the
    # output is as expected on Linux) will be:
    # Run: 0
    # Created queue
    # Grabbed item from queue: 0
    # ...
    # Grabbed item from queue: 29
    # Created processes
    # Q is empty
    # Run: 1
    # Created queue
    # Grabbed item from queue: 30
    # ...
    # Grabbed item from queue: 59
    # Created processes
    # Q is empty
    # Run: 2
    # Created queue
    # Created processes
    # <no further output>
#    for p in processes:
#        p.join()

for i in range(100):
    _do(i)