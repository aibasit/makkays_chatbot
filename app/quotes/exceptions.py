"""Exceptions for Quote Builder."""

from __future__ import annotations

from uuid import UUID


class QuoteError(Exception):
    """Base class for quote module failures."""


class IncompleteQuoteSlotsError(QuoteError):
    """Raised when required quote inputs are missing."""


class PricingDataMissingError(QuoteError):
    """Raised when one or more products have no pricing row."""

    def __init__(self, missing_product_ids: list[UUID]) -> None:
        self.missing_product_ids = missing_product_ids
        ids = ", ".join(str(item) for item in missing_product_ids)
        super().__init__(f"Missing pricing data for product IDs: {ids}")


class QuoteCurrencyMismatchError(QuoteError):
    """Raised when selected products have mixed currencies."""


class QuotePersistenceError(QuoteError):
    """Raised when a quote cannot be persisted."""
