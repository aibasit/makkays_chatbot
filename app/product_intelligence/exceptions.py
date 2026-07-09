"""Product Intelligence domain exceptions."""


class ProductIntelligenceError(Exception):
    """Base exception for product intelligence failures."""


class ProductNotFoundError(ProductIntelligenceError):
    """Raised when a referenced product ID does not exist for the tenant."""


class CompatibilityRuleNotFoundError(ProductIntelligenceError):
    """Raised when no explicit compatibility rule exists (caller falls back to LLM inference)."""


class InsufficientProductsForComparisonError(ProductIntelligenceError):
    """Raised when fewer than two products are supplied for comparison."""
