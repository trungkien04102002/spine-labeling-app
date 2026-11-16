"""Size the CPU thread pools to the CPUs this container may actually use.

In containers, os.cpu_count() reports every host core while the cgroup quota
may allow only a fraction. PyTorch and BLAS start one thread per reported core,
and the resulting oversubscription slows CPU inference several-fold. This
module must be imported before numpy or torch so the environment variables
take effect. Explicitly set variables are never overridden.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")


def cgroup_cpu_limit() -> int | None:
    """Whole CPUs the cgroup quota allows, or None if there is no quota."""
    try:  # cgroup v2: "<quota> <period>", quota "max" when unlimited
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return max(1, math.ceil(int(quota) / int(period)))
        return None
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0 and period > 0:
            return max(1, math.ceil(quota / period))
    except (OSError, ValueError):
        pass
    return None


def apply() -> int | None:
    """Cap the thread pools at the cgroup limit when it is below the core count."""
    limit = cgroup_cpu_limit()
    if limit is None or limit >= (os.cpu_count() or limit):
        return None
    for var in _VARS:
        os.environ.setdefault(var, str(limit))
    return limit


apply()
