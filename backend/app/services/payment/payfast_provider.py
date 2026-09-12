import hmac
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import requests

from app.config import (
    BACKEND_BASE_URL,
    PAYMENT_API_BASE_URL,
    PAYMENT_MERCHANT_ID,
    PAYMENT_SECRET,
    PAYMENT_WEBHOOK_SECRET,
)
from app.services.payment.base import CheckoutSession, PaymentProvider, WebhookEvent

logger = logging.getLogger("talentnest.payment.payfast")


class PayFastProvider(PaymentProvider):
    """
    PayFast Pakistan (apps.net.pk) integration.

    PayFast Pakistan's hosted-checkout flow (confirmed against PayFast's
    own official integrations, e.g. https://gopayfast.com/docs and the
    reference client libraries built on top of ipguat/ipg1.apps.net.pk) is:

      1. Server calls GetAccessToken with MERCHANT_ID + SECURED_KEY + the
         order's BASKET_ID/TXNAMT/CURRENCY_CODE to get a short-lived
         access token.
      2. The browser is sent to PayFast's hosted checkout page
         (Ecommerce/api/Transaction/PostTransaction) with that token and
         the same order details, plus SUCCESS_URL/FAILURE_URL (browser
         redirects) and CHECKOUT_URL - the *server-to-server* notify URL
         PayFast posts the final transaction result to. The customer
         enters card/wallet details there.
      3. PayFast independently POSTs the transaction result to
         CHECKOUT_URL (BASKET_ID, TRANSACTION_ID, ERR_CODE, TXNAMT, ...).
         That server-to-server POST - never the browser landing on
         SUCCESS_URL - is what activates the subscription.

    PayFast Pakistan does not publish an HMAC/signature scheme for that
    notification. Authenticity is instead established the way PayFast's
    own reference integrations do it:
      - CHECKOUT_URL is a private, unguessable URL we generate ourselves,
        carrying a shared secret (PAYMENT_WEBHOOK_SECRET) that only our
        backend and PayFast (who we told it to) ever see.
      - The BASKET_ID in the notification must match a PENDING Payment
        row we created ourselves at checkout time.
      - The TXNAMT in the notification must match that Payment row's
        amount to the cent - a tampered amount is rejected outright.
      - ERR_CODE "00" ("Processed OK" per PayFast's published error-code
        table) is the only value treated as a successful payment.

    All PayFast-specific request/response shapes are isolated to this
    file; nothing outside app/services/payment should ever need to know
    about PayFast's field names.
    """

    name = "payfast"

    ACCESS_TOKEN_ENDPOINT = "/Ecommerce/api/Transaction/GetAccessToken"
    # Documented hosted-checkout submission endpoint (see e.g.
    # https://github.com/RaRashed/payfast-php and
    # https://github.com/zfhassaan/payfast) - NOT "PurchaseTransaction",
    # which does not appear anywhere in PayFast's own docs or reference
    # integrations.
    CHECKOUT_PAGE = "/Ecommerce/api/Transaction/PostTransaction"

    # PayFast's published error/status codes (gopayfast.com/docs). "00" is
    # the only code that means the payment actually succeeded - everything
    # else (pending, timeout, insufficient balance, invalid OTP, etc.) must
    # never activate a subscription.
    SUCCESS_ERR_CODE = "00"

    def _get_access_token(self, *, basket_id: str, amount: float, currency: str) -> str:
        if not PAYMENT_MERCHANT_ID or not PAYMENT_SECRET:
            raise RuntimeError(
                "PayFast is not configured. Set PAYMENT_MERCHANT_ID and "
                "PAYMENT_SECRET (the PayFast secured key) before selecting "
                "PAYMENT_PROVIDER=payfast."
            )

        response = requests.post(
            f"{PAYMENT_API_BASE_URL}{self.ACCESS_TOKEN_ENDPOINT}",
            data={
                "MERCHANT_ID": PAYMENT_MERCHANT_ID,
                "SECURED_KEY": PAYMENT_SECRET,
                "BASKET_ID": basket_id,
                "TXNAMT": f"{amount:.2f}",
                "CURRENCY_CODE": currency,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        token = data.get("ACCESS_TOKEN")
        if not token:
            logger.error(f"PayFast GetAccessToken did not return a token: {data}")
            raise RuntimeError("PayFast did not return an access token for this checkout.")

        return token

    def _webhook_url(self) -> str:
        """
        The private, backend-only URL PayFast is told to POST the final
        transaction result to (PayFast's "CHECKOUT_URL" field). Carries a
        shared secret as a query parameter so we can tell a genuine
        PayFast notification apart from a request forged by a third party
        who merely guesses a BASKET_ID - PayFast does not sign this
        notification itself, so this is the layer that makes the endpoint
        unguessable.
        """
        if not PAYMENT_WEBHOOK_SECRET:
            raise RuntimeError(
                "PAYMENT_WEBHOOK_SECRET is not configured; refusing to register "
                "a PayFast notify URL that nothing can authenticate."
            )
        return f"{BACKEND_BASE_URL}/payment/webhook?token={quote(PAYMENT_WEBHOOK_SECRET)}"

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
        access_token = self._get_access_token(
            basket_id=transaction_id,
            amount=amount,
            currency=currency,
        )

        order_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Documented PostTransaction fields for the hosted checkout
        # redirect. CHECKOUT_URL is the server-to-server notify URL (our
        # webhook); SUCCESS_URL/FAILURE_URL are only where the *browser*
        # is redirected and never activate anything by themselves.
        params = {
            "MERCHANT_ID": PAYMENT_MERCHANT_ID,
            "ACCESS_TOKEN": access_token,
            "BASKET_ID": transaction_id,
            "TXNAMT": f"{amount:.2f}",
            "CURRENCY_CODE": currency,
            "ORDER_DATE": order_date,
            "SUCCESS_URL": return_url,
            "FAILURE_URL": cancel_url,
            "CHECKOUT_URL": self._webhook_url(),
        }

        checkout_url = f"{PAYMENT_API_BASE_URL}{self.CHECKOUT_PAGE}?{urlencode(params)}"

        return CheckoutSession(checkout_url=checkout_url, transaction_id=transaction_id)

    def verify_webhook(
        self,
        payload: bytes,
        headers: dict,
        form: dict | None = None,
        query: dict | None = None,
    ) -> WebhookEvent:
        data = form or {}
        query = query or {}

        # --- 1. Authenticate the caller -----------------------------------
        # PayFast Pakistan does not sign this notification, so the shared
        # secret embedded in the CHECKOUT_URL we registered at checkout
        # time (see _webhook_url) is what stops a third party who merely
        # guesses/observes a BASKET_ID from forging a "payment succeeded"
        # notification.
        if not PAYMENT_WEBHOOK_SECRET:
            raise ValueError(
                "PAYMENT_WEBHOOK_SECRET is not configured; refusing to trust "
                "an unauthenticated PayFast webhook."
            )

        provided_token = query.get("token") or headers.get("x-webhook-token")
        if not provided_token or not hmac.compare_digest(provided_token, PAYMENT_WEBHOOK_SECRET):
            raise ValueError("PayFast webhook token missing or invalid.")

        # --- 2. Parse PayFast's documented fields --------------------------
        # PayFast Pakistan's hosted-checkout notification uses the same
        # field names as PostTransaction/GetAccessToken (BASKET_ID,
        # TXNAMT, ERR_CODE, TRANSACTION_ID). Some integrations receive
        # these lower-cased, so both are accepted.
        transaction_id = data.get("BASKET_ID") or data.get("basket_id")
        err_code = str(data.get("ERR_CODE") or data.get("err_code") or "").strip()
        provider_transaction_id = (
            data.get("TRANSACTION_ID") or data.get("transaction_id") or transaction_id
        )
        raw_amount = data.get("TXNAMT") or data.get("txnamt") or data.get("amount")

        if not transaction_id or not err_code:
            raise ValueError("Malformed PayFast webhook payload (missing BASKET_ID/ERR_CODE).")

        amount: float | None = None
        if raw_amount is not None:
            try:
                amount = float(raw_amount)
            except (TypeError, ValueError):
                raise ValueError(f"Malformed PayFast webhook payload: unparseable TXNAMT={raw_amount!r}")

        status = "paid" if err_code == self.SUCCESS_ERR_CODE else "failed"

        return WebhookEvent(
            transaction_id=transaction_id,
            status=status,
            raw={**data, "PROVIDER_TRANSACTION_ID": provider_transaction_id},
            amount=amount,
        )

    def cancel_provider_subscription(self, provider_subscription_id: str | None) -> bool:
        """
        PayFast Pakistan's hosted-checkout integration (GetAccessToken +
        PostTransaction, see the class docstring above) has no
        tokenized/automatic recurring-billing API: every charge - the
        first subscribe AND every later renewal - is its own one-off,
        customer-present PostTransaction. There is no server-side
        "subscription" object stored at PayFast for a given company, and
        PayFast's published docs/reference integrations (gopayfast.com,
        github.com/RaRashed/payfast-php, github.com/zfhassaan/payfast)
        expose no cancel-subscription or stop-billing endpoint to call.

        So there is nothing to cancel provider-side: "cancellation" here
        is purely local (Subscription.cancel_at_period_end) and simply
        means the company doesn't click "Renew" again. This override
        exists to make that explicit rather than inventing an endpoint
        that does not exist in PayFast's documentation.
        """
        logger.info(
            "PayFast has no provider-side subscription object to cancel "
            f"(transaction_id={provider_subscription_id}); relying entirely "
            "on local cancel_at_period_end."
        )
        return False
