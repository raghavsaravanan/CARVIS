"""Fail-closed authentication for the Vapi tool webhook (M2 Track A1).

The webhook credential is the shared secret Vapi sends in the ``X-Vapi-Secret`` header. There is
no unauthenticated path: when no secret is configured every webhook request is rejected, and every
environment other than ``local`` refuses to boot without one.

``CARVIS_ENV`` selects the environment (``local``, ``staging`` or ``production``). When it is
unset the service assumes ``production`` so that a deploy missing configuration fails closed.
"""

from __future__ import annotations

import hmac
import os

WEBHOOK_SECRET_ENV = "VAPI_WEBHOOK_SECRET"
WEBHOOK_SECRET_HEADER = "x-vapi-secret"
ENVIRONMENT_ENV = "CARVIS_ENV"
LOCAL = "local"
ENVIRONMENTS = (LOCAL, "staging", "production")
DEFAULT_ENVIRONMENT = "production"


class WebhookConfigurationError(RuntimeError):
    """Raised at startup when the webhook cannot be served safely."""


def deployment_environment() -> str:
    """Return the validated deployment environment; unset means production."""
    raw = (os.getenv(ENVIRONMENT_ENV) or "").strip().lower()
    environment = raw or DEFAULT_ENVIRONMENT
    if environment not in ENVIRONMENTS:
        # The value itself is not echoed, in case a credential was pasted into the wrong variable.
        raise WebhookConfigurationError(f"{ENVIRONMENT_ENV} must be one of {', '.join(ENVIRONMENTS)}.")
    if environment == LOCAL and (os.getenv("RENDER") or "").strip():
        raise WebhookConfigurationError(f"{ENVIRONMENT_ENV}=local is not allowed on Render.")
    return environment


def configured_secret() -> str:
    """The configured webhook secret, stripped; empty when unset or blank."""
    return (os.getenv(WEBHOOK_SECRET_ENV) or "").strip()


def require_webhook_secret_at_boot() -> str:
    """Refuse to start outside local without a webhook secret. Returns the environment."""
    environment = deployment_environment()
    if environment != LOCAL and not configured_secret():
        raise WebhookConfigurationError(
            f"{WEBHOOK_SECRET_ENV} is required when {ENVIRONMENT_ENV}={environment}. "
            f"Set it, or set {ENVIRONMENT_ENV}=local for local development."
        )
    return environment


def webhook_request_authorized(presented: str | None) -> bool:
    """Constant-time check of the presented header against the configured secret.

    Fails closed: no configured secret, or no presented value, is never authorized.
    """
    expected = configured_secret()
    if not expected or presented is None:
        return False
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input, and an
    # attacker-controlled header must produce a 401, never a 500.
    return hmac.compare_digest(
        presented.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    )
