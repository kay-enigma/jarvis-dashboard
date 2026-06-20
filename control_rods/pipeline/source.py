"""
Data source abstraction.

The frontend and API never know or care where the plan data physically
comes from. They depend on this `PlanSource` interface, not on Google.
That indirection is what lets the same pipeline run against:

    - a live Google Sheet           (production)
    - a local CSV/JSON snapshot     (dev, CI, demos, offline)

and is the single most important design decision in the repo from a
"this person can architect" standpoint: the expensive, auth-bound,
flaky dependency (Google) sits behind a seam, so everything else is
trivially testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from control_rods.schema import Plan


class PlanSource(ABC):
    """Anything that can produce a validated Plan."""

    @abstractmethod
    def load(self) -> Plan:
        """Fetch raw data, validate it, return a Plan.

        Implementations MUST return a fully-validated Plan or raise.
        They must never return partially-valid data - a bad row in the
        sheet should fail loudly here, not surface as a broken dashboard.
        """
        raise NotImplementedError

    @property
    def description(self) -> str:
        """Human-readable label for logs / the dashboard footer."""
        return self.__class__.__name__
