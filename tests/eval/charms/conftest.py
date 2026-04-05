"""Prevent pytest from collecting gold-standard charm test files.

The test files inside gold-standard directories (e.g. gold-claude/tests/)
are part of the charm implementation being evaluated, not tests that
should be run by our test suite.
"""

collect_ignore_glob = ["*/gold-*/tests/*"]
