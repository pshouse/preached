"""Importing the test package arms the cache guard for unittest.

``python -m unittest discover -s tests`` does not import this package.
Each test module calls ``install`` itself (one import line, idempotent),
so discovery, a ``-p`` pattern that skips ``test_cache_guard``, ``python
-m unittest test_x`` from inside ``tests/``, and ``python tests/test_x.py``
are armed. Calling ``install`` here as well does not arm a second time.
"""

from .cache_guard import install

install()
