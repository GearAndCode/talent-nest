from functools import lru_cache

from app.config import PAYMENT_PROVIDER
from app.services.payment.base import PaymentProvider
from app.services.payment.payfast_provider import PayFastProvider


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """
    Single place that decides which gateway implementation to use, driven
    entirely by the PAYMENT_PROVIDER environment variable. Swapping
    gateways (or adding a second one later) never requires touching
    routers/subscription.py.

    Only real, officially-documented providers are wired in here. There is
    intentionally NO mock/simulated provider: if PAYMENT_PROVIDER is unset
    or credentials are missing, checkout creation fails loudly with a clear
    error instead of silently granting access.
    """
    provider = (PAYMENT_PROVIDER or "payfast").lower()

    if provider == "payfast":
        return PayFastProvider()

    raise ValueError(
        f"Unknown PAYMENT_PROVIDER '{provider}'. Supported values: 'payfast'."
    )
