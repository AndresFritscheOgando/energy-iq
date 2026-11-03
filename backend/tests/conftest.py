"""Shared pytest configuration: Hypothesis profiles for property tests.

``ENERGYIQ_HYPOTHESIS_PROFILE`` picks the profile. The default ``energyiq``
profile is derandomized and keeps no example database, so every run tries the
same examples. ``deep`` searches 2000 random examples per property and keeps
the local example database. The profile is loaded explicitly so that
Hypothesis never switches to its own ``ci`` profile when a ``CI`` variable is
set. An unknown name raises ``InvalidArgument`` and stops the session.
"""

import os

from hypothesis import settings

PROFILE_ENV_VAR = "ENERGYIQ_HYPOTHESIS_PROFILE"
DEFAULT_PROFILE = "energyiq"

# Inherit from the built in default, never from whichever profile Hypothesis
# auto loaded (its ``ci`` profile suppresses a health check).
_BASE = settings.get_profile("default")

settings.register_profile(
    "energyiq",
    parent=_BASE,
    max_examples=200,
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "deep",
    parent=_BASE,
    max_examples=2000,
    derandomize=False,
    deadline=None,
    print_blob=True,
)
settings.load_profile(os.environ.get(PROFILE_ENV_VAR, DEFAULT_PROFILE))
