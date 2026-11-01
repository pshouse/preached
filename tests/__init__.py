"""Importing the test package arms the cache guard for unittest.

``python -m unittest discover -s tests`` does not import this package.
``tests/test_cache_guard.py`` calls ``install`` itself so that discovery
still arms the guard.
"""

from .cache_guard import install

install()
