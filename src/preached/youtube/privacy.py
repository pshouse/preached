"""Privacy hook for transcript words: the W3-PRIV redactor.

``redact(words, config=None, source=None)`` flags likely congregant names as
``[name]`` and keeps every timestamp. It is assisted, not guaranteed: a person
must read the ``review()`` list before a sermon is published. The pipeline
passes ``source=<video id>`` so ``drop`` windows apply. Do not add a name list
or a rule here; they live in ``preached.privacy``.
"""

from preached.privacy import redact  # noqa: F401
