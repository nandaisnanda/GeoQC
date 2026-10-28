"""Hypothesis profiles for the property-based check suite.

``default`` explores 200 examples per test for local runs. ``ci`` is smaller and
derandomized so pull-request runs stay fast and reproducible. Select a profile with
``HYPOTHESIS_PROFILE``; GitHub Actions sets ``CI`` and gets ``ci`` automatically.
"""

import os

from hypothesis import HealthCheck, settings

_SLOW_CHECKS = (HealthCheck.too_slow, HealthCheck.data_too_large)

settings.register_profile(
    "default",
    max_examples=200,
    deadline=None,
    suppress_health_check=_SLOW_CHECKS,
)
settings.register_profile(
    "ci",
    max_examples=40,
    deadline=None,
    derandomize=True,
    print_blob=True,
    suppress_health_check=_SLOW_CHECKS,
)
settings.load_profile(
    os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "default")
)
