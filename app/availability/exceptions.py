"""Exceptions for availability checking."""

from __future__ import annotations


class AvailabilityCheckError(Exception):
    """Base error for availability checks."""


class ERPConnectionError(AvailabilityCheckError):
    """Raised when an ERP availability check fails."""
