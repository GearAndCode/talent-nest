from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CheckoutSession:
    """Result of starting a checkout with a payment gateway."""

    checkout_url: str
    transaction_id: str


@dataclass
class WebhookEvent:
    """
    A payment gateway webhook/IPN event, normalized to a provider-agnostic
    shape so app.routers.subscription doesn't need to know which gateway
    sent it.
    """

    transaction_id: str
    status: str  # normalized to "paid" | "failed" | "cancelled"
    raw: Any
    # The amount the gateway says was actually charged for this
    # transaction, when the notification includes one. app.routers.
    # subscription compares this against the pending Payment row's amount
    # so a tampered/incorrect amount in the notification can never
    # activate a subscription. None if the gateway's payload didn't
    # include a parseable amount (verification then relies solely on the
    # transaction id match + provider status).
    amount: Optional[float] = None


class PaymentProvider(ABC):
    """
    Provider-specific logic (PayFast, or any future gateway) lives entirely
    behind this interface. Nothing outside app/services/payment should ever
    branch on which provider is configured.
    """

    name: str = "base"

    @abstractmethod
    def create_checkout_session(
        self,
        *,
        company_id: int,
        company_email: str,
        plan_code: str,
        plan_name: str,
        amount: float,
        currency: str,
        transaction_id: str,
        return_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        """Start a hosted checkout and return the URL to redirect the user to."""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        headers: dict,
        form: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> WebhookEvent:
        """
        Validate the authenticity of an incoming webhook/IPN (signature,
        shared secret, etc.) and return a normalized WebhookEvent. Must
        raise ValueError if the event cannot be verified.
        """
        raise NotImplementedError

    def cancel_provider_subscription(self, provider_subscription_id: Optional[str]) -> bool:
        """
        Best-effort, provider-side mirror of a local cancellation, for
        gateways that maintain their own recurring-billing subscription
        object which must be told to stop auto-charging.

        This is intentionally NOT abstract and defaults to a no-op
        returning False ("nothing to do provider-side"): our local
        Subscription row (cancel_at_period_end / current_period_end) is
        always the source of truth for entitlement, so a provider that
        has no such concept - or that fails this call - must never block
        or reverse the local cancellation. Override this only for a
        gateway whose CURRENT, documented API actually exposes a
        cancel-subscription endpoint.
        """
        return False
