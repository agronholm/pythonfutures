#!/usr/bin/env python
# coding: utf-8
from warnings import warn
import os.path
import sys

if sys.version_info[0] > 2:
    pip_message = ('This may be due to an out of date pip. '
                   'Make sure you have pip >= 9.0.1.\n')
    try:
        import pip
        pip_version = tuple([int(x) for x in pip.__version__.split('.')[:3]])
        if pip_version < (9, 0, 1) :
            pip_message = ('Your pip version is out of date, '
                           'please install pip >= 9.0.1. \n'
                           'pip {} detected.'.format(pip.__version__))
        else:
            # pip is new enough - it must be something else
            pip_message = ''
    except Exception:
        pass



extras = {}
try:
    from setuptools import setup
    extras['zip_safe'] = False
except ImportError:
    from distutils.core import setup

here = os.path.dirname(__file__)
with open(os.path.join(here, 'README.rst')) as f:
    readme = f.read()

setup(name='futures',
      version='3.2.0',
      description='Backport of the concurrent.futures package from Python 3',
      long_description=readme,
      author='Brian Quinlan',
      author_email='brian@sweetapp.com',
      maintainer=u'Alex Grönholm',
      maintainer_email='alex.gronholm@nextday.fi',
      url='https://github.com/agronholm/pythonfutures',
      packages=['concurrent', 'concurrent.futures'],
      license='PSF',
      classifiers=['License :: OSI Approved :: Python Software Foundation License',
                   'Development Status :: 5 - Production/Stable',
                   'Intended Audience :: Developers',
                   'Programming Language :: Python :: 2.6',
                   'Programming Language :: Python :: 2.7',
                   'Programming Language :: Python :: 2 :: Only'],
      **extras
      )
