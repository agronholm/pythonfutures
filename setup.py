#!/usr/bin/env python
# coding: utf-8
from __future__ import print_function

import os.path
import sys

if sys.version_info[0] > 2:
    print('This backport is meant only for Python 2.\n'
          'It does not work on Python 3, and Python 3 users do not need it '
          'as the concurrent.futures package is available in the standard library.\n'
          'For projects that work on both Python 2 and 3, the dependency needs to be conditional '
          'on the Python version, like so:\n'
          "extras_require={':python_version == \"2.7\"': ['futures']}",
          file=sys.stderr)
    sys.exit(1)

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
      version='3.4.0',
      description='Backport of the concurrent.futures package from Python 3',
      long_description=readme,
      author='Brian Quinlan',
      author_email='brian@sweetapp.com',
      maintainer=u'Alex Grönholm',
      maintainer_email='alex.gronholm@nextday.fi',
      url='https://github.com/agronholm/pythonfutures',
      packages=['concurrent', 'concurrent.futures'],
      python_requires='>=2.6, <3',
      license='PSF',
      classifiers=['License :: OSI Approved :: Python Software Foundation License',
                   'Development Status :: 5 - Production/Stable',
                   'Intended Audience :: Developers',
                   'Programming Language :: Python :: 2.6',
                   'Programming Language :: Python :: 2.7',
                   'Programming Language :: Python :: 2 :: Only'],
      **extras
      )
