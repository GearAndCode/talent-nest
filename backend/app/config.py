from dotenv import load_dotenv
import os


load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# Google OAuth / Google Identity Services
GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    "1034068374242-qumdm0600c5m5h2j10rlaurnn4m0u9o4.apps.googleusercontent.com",
)


# ============================================================
# App environment (sandbox/development vs production)
# ============================================================
# Drives which PayFast host we talk to by default and how strictly we
# validate PayFast credentials at startup. Accepted values: "production"
# or "sandbox" (anything else - unset, "development", "test", etc. - is
# treated as sandbox, i.e. never silently treated as production).
ENVIRONMENT = os.getenv("ENVIRONMENT", "sandbox").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"


# ============================================================
# SaaS Billing / Payment Gateway (PayFast Pakistan)
# ============================================================
# Pakistan-based merchants generally cannot use Stripe. PayFast Pakistan
# (apps.net.pk) is the only provider wired in - see
# app/services/payment/payfast_provider.py. There is no mock/simulated
# provider: without real credentials, checkout creation will fail with a
# clear error rather than pretend to succeed.
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "payfast")

# PayFast merchant ID, issued when your merchant account is approved.
# NEVER hardcode this - it must always come from the environment.
PAYMENT_MERCHANT_ID = os.getenv("PAYMENT_MERCHANT_ID")

# PayFast "Secured Key" for your merchant account (used to request access
# tokens for checkout - NOT the same as the webhook/IPN secret below).
# NEVER hardcode this - it must always come from the environment.
PAYMENT_SECRET = os.getenv("PAYMENT_SECRET")

# Optional separate API key, if your PayFast integration tier issues one.
PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY")

# Secret/token PayFast gives you to validate incoming IPN/webhook calls.
# NEVER hardcode this - it must always come from the environment.
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET")

# Base URL of PayFast's API.
#   Sandbox:    https://ipguat.apps.net.pk
#   Production: https://ipg1.apps.net.pk
# The default is picked from ENVIRONMENT so a production deployment that
# forgets to set PAYMENT_API_BASE_URL still talks to PayFast's live host,
# not sandbox - it never silently falls back to the wrong environment.
# An explicit PAYMENT_API_BASE_URL always wins, but see the guard below:
# it is rejected if it points at the sandbox host while ENVIRONMENT=production.
_PAYFAST_SANDBOX_BASE_URL = "https://ipguat.apps.net.pk"
_PAYFAST_PRODUCTION_BASE_URL = "https://ipg1.apps.net.pk"

PAYMENT_API_BASE_URL = os.getenv(
    "PAYMENT_API_BASE_URL",
    _PAYFAST_PRODUCTION_BASE_URL if IS_PRODUCTION else _PAYFAST_SANDBOX_BASE_URL,
)

# Public URL of the TalentNest frontend, used to build the return/cancel
# URLs PayFast redirects the browser to after checkout. This redirect is
# NOT what activates the subscription - the webhook is.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

# Public URL of THIS backend, used to build the webhook/IPN URL registered
# with PayFast.
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")


def validate_payment_config() -> None:
    """
    Fail fast, with a clear error, if this process is about to run in
    production without everything PayFast checkout/webhooks need.

    Called at backend startup (see app/main.py). Intentionally a no-op in
    sandbox/development: missing credentials there just mean checkout is
    disabled until PayFastProvider._get_access_token raises its own
    RuntimeError when someone actually tries to check out.
    """
    if not IS_PRODUCTION:
        return

    if (PAYMENT_PROVIDER or "").lower() != "payfast":
        # A future non-PayFast provider would need its own production
        # validation here - nothing to check for an unrecognized provider,
        # get_payment_provider() will already reject it.
        return

    missing: list[str] = []

    if not PAYMENT_MERCHANT_ID:
        missing.append("PAYMENT_MERCHANT_ID")
    if not PAYMENT_SECRET:
        missing.append("PAYMENT_SECRET")
    if not PAYMENT_WEBHOOK_SECRET:
        missing.append("PAYMENT_WEBHOOK_SECRET")
    if not FRONTEND_BASE_URL or "localhost" in FRONTEND_BASE_URL:
        missing.append("FRONTEND_BASE_URL (must be the real production frontend URL, not localhost)")
    if not BACKEND_BASE_URL or "localhost" in BACKEND_BASE_URL:
        missing.append("BACKEND_BASE_URL (must be the real production backend URL, not localhost)")
    if PAYMENT_API_BASE_URL == _PAYFAST_SANDBOX_BASE_URL:
        missing.append(
            "PAYMENT_API_BASE_URL (currently set to PayFast's sandbox host "
            f"{_PAYFAST_SANDBOX_BASE_URL}; production must use "
            f"{_PAYFAST_PRODUCTION_BASE_URL})"
        )

    if missing:
        raise RuntimeError(
            "ENVIRONMENT=production but the following PayFast/billing "
            "settings are missing or invalid: "
            + "; ".join(missing)
            + ". Set these environment variables before starting the app "
            "in production - refusing to start with an unsafe payment "
            "configuration."
        )
