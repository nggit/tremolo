#!/usr/bin/env python3

from setuptools import setup

with open('README.md', 'r') as f:
    long_description = f.read()

setup(
    name='tremolo',
    version='0.0.308',
    license='MIT',
    author='nggit',
    author_email='contact@anggit.com',
    description=('Tremolo is a stream-oriented, asynchronous, '
                 'programmable HTTP server written in pure Python. '
                 'It can also serve as an ASGI server.'),
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/nggit/tremolo',
    packages=['tremolo'],
    package_data={'': ['lib/*', 'lib/h1parser/*']},
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
    ],
)
