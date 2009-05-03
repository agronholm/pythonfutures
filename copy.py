#!/usr/bin/env python

import functools
import futures.thread as futures
import shutil
import os
import os.path

def copy_many(destination, sources_files):
    for source_file in sources_files:
        copied_files = []
        try:
            shutil.copy2(source_file, destination)
        except IOError, e:
            for delete_file in copied_files:
                try:
                    os.remove(delete_file)
                except:
                    pass
            raise
        else:
            copied_files.append(source_files)

p = futures.ThreadPoolExecutor(max_threads=15)

def copy_many(destination, sources_files):
    copies = p.run(
        (functools.partial(shutil.copy2, sources_file, destination)
         for sources_file in sources_files),
        run_until=futures.FIRST_EXCEPTION)

    if copies.has_exception_futures():
        copies.cancel()
        for f in map(copies:
            if not f.exception():
                
        functools.partial(os.path.)
        raise copies.get_exception_futures()[0].exception()

"""
def copy_many(sources_and_destinations):
    copies = p.run(
        (functools.partial(shutil.copytree, source, destination)
         for source, destination in sources_and_destinations),
        run_until=futures.FIRST_EXCEPTION)

    print('copies:', copies)
    if copies.has_exception_futures():
        print('HAS EXCEPTIONS')
        copies.cancel(exit_running=True, wait_unit_finished=True)
        p.run(
            (functools.partial(shutil.rmtree, destination, ignore_errors=True)
            for _, destination in sources_and_destinations),
            run_until=futures.ALL_COMPLETED)
        raise copies.get_exception_futures()[0].exception()
    print('copies:', copies)


copy_many([('source1', 'destination/source1'),
           ('source2', 'destination/source2'),
           ('source3', 'destination/source3')])
"""

copy_many2('destination', ['source1', 'source2', 'source3', 'source4', 'source5',
                          'source6', 'source7', 'source8', 'source9', 'source11'])