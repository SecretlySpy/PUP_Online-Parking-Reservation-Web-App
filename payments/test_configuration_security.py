"""Security regression tests for payment and deployment configuration."""

import hashlib
import hmac
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from config.checks import check_privileged_configuration

from .gateway import is_simulation_enabled, verify_webhook_signature


class PaymentModeTests(SimpleTestCase):
    """The simulator requires deliberate intent and a development runtime."""

    @override_settings(
        DEBUG=True,
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMONGO_SECRET_KEY="",
    )
    def test_simulation_requires_explicit_debug_only_opt_in(self):
        self.assertTrue(is_simulation_enabled())

    @override_settings(
        DEBUG=False,
        TESTING=False,
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMONGO_SECRET_KEY="",
    )
    def test_simulation_is_disabled_when_debug_is_false(self):
        self.assertFalse(is_simulation_enabled())

    @override_settings(
        DEBUG=True,
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMONGO_SECRET_KEY="sk_test_configured",
    )
    def test_simulation_cannot_bypass_configured_gateway(self):
        self.assertFalse(is_simulation_enabled())


class WebhookVerificationTests(SimpleTestCase):
    """Missing secrets reject events except in the isolated simulator path."""

    def setUp(self):
        self.factory = RequestFactory()
        self.body = b'{"data":{"id":"evt_test"}}'

    def _request(self, signature=""):
        # RequestFactory preserves the raw body needed by PayMongo's HMAC.
        return self.factory.post(
            "/payments/webhook/",
            data=self.body,
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE=signature,
        )

    @override_settings(
        DEBUG=False,
        TESTING=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="",
    )
    def test_missing_webhook_secret_fails_closed(self):
        self.assertFalse(verify_webhook_signature(self._request()))

    @override_settings(
        DEBUG=True,
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMONGO_SECRET_KEY="",
        PAYMONGO_WEBHOOK_SECRET="",
    )
    def test_unsigned_webhook_is_allowed_only_for_explicit_simulation(self):
        self.assertTrue(verify_webhook_signature(self._request()))

    @override_settings(
        DEBUG=False,
        TESTING=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_real_test_value",
        PAYMONGO_WEBHOOK_TOLERANCE_SECONDS=300,
    )
    @patch("payments.gateway.time.time", return_value=1720000030)
    def test_matching_webhook_signature_is_accepted(self, _mocked_time):
        timestamp = "1720000000"
        signed_payload = timestamp.encode() + b"." + self.body
        digest = hmac.new(
            b"whsec_real_test_value", signed_payload, hashlib.sha256
        ).hexdigest()
        request = self._request(f"t={timestamp},li={digest}")
        self.assertTrue(verify_webhook_signature(request))

    @override_settings(
        DEBUG=False,
        TESTING=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_real_test_value",
        PAYMONGO_WEBHOOK_TOLERANCE_SECONDS=300,
    )
    @patch("payments.gateway.time.time", return_value=1720000030)
    def test_live_gateway_rejects_valid_test_mode_signature(self, _mocked_time):
        timestamp = "1720000000"
        digest = hmac.new(
            b"whsec_real_test_value",
            timestamp.encode() + b"." + self.body,
            hashlib.sha256,
        ).hexdigest()
        self.assertFalse(
            verify_webhook_signature(self._request(f"t={timestamp},te={digest}"))
        )

    @override_settings(
        DEBUG=False,
        TESTING=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_test_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_real_test_value",
        PAYMONGO_WEBHOOK_TOLERANCE_SECONDS=300,
    )
    @patch("payments.gateway.time.time", return_value=1720000400)
    def test_stale_signature_is_rejected(self, _mocked_time):
        timestamp = "1720000000"
        digest = hmac.new(
            b"whsec_real_test_value",
            timestamp.encode() + b"." + self.body,
            hashlib.sha256,
        ).hexdigest()
        self.assertFalse(
            verify_webhook_signature(self._request(f"t={timestamp},te={digest}"))
        )


@override_settings(
    SITE_BASE_URL="https://parking.example.edu",
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.example.edu",
)
class DeploymentCheckTests(SimpleTestCase):
    """Unsafe privileged/payment combinations surface as deploy errors."""

    def _error_ids(self):
        return {error.id for error in check_privileged_configuration(None)}

    @override_settings(
        ADMIN_SIGNUP_ENABLED=False,
        ADMIN_SIGNUP_CODE="",
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
    )
    def test_complete_configuration_passes_custom_checks(self):
        self.assertEqual(self._error_ids(), set())

    @override_settings(
        ADMIN_SIGNUP_ENABLED=True,
        ADMIN_SIGNUP_CODE="short",
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
    )
    def test_weak_admin_code_is_reported(self):
        self.assertIn("parking.E001", self._error_ids())

    @override_settings(
        ADMIN_SIGNUP_ENABLED=False,
        ADMIN_SIGNUP_CODE="",
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMONGO_SECRET_KEY="",
        PAYMONGO_PUBLIC_KEY="",
        PAYMONGO_WEBHOOK_SECRET="",
    )
    def test_simulation_and_missing_credentials_are_reported(self):
        error_ids = self._error_ids()
        self.assertIn("parking.E002", error_ids)
        self.assertIn("parking.E003", error_ids)

    @override_settings(
        ADMIN_SIGNUP_ENABLED=True,
        ADMIN_SIGNUP_CODE="strong-admin-enrollment-code-2026",
        ADMIN_SIGNUP_MAX_ATTEMPTS=0,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
    )
    def test_invalid_admin_throttle_is_reported(self):
        self.assertIn("parking.E004", self._error_ids())

    @override_settings(
        ADMIN_SIGNUP_ENABLED=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
        SITE_BASE_URL="http://127.0.0.1:8000",
    )
    def test_non_public_site_url_is_reported(self):
        self.assertIn("parking.E005", self._error_ids())

    @override_settings(
        ADMIN_SIGNUP_ENABLED=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_live_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    def test_non_delivery_email_backend_is_reported(self):
        self.assertIn("parking.E006", self._error_ids())

    @override_settings(
        ADMIN_SIGNUP_ENABLED=False,
        PAYMENT_SIMULATION_ENABLED=False,
        PAYMONGO_SECRET_KEY="sk_live_configured",
        PAYMONGO_PUBLIC_KEY="pk_test_configured",
        PAYMONGO_WEBHOOK_SECRET="whsec_configured_value",
    )
    def test_mismatched_gateway_key_modes_are_reported(self):
        self.assertIn("parking.E003", self._error_ids())
