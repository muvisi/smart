from django.core import mail
from django.test import TestCase, override_settings

from .tasks import send_etims_health_report


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="gx-etims@madison.co.ke",
    TEST_EMAIL_RECIPIENTS=["operations@madison.co.ke"],
    ETIMS_ENVIRONMENT="Production",
)
class EtimsHealthReportTests(TestCase):
    def test_sends_branded_multipart_health_report(self):
        result = send_etims_health_report()

        self.assertEqual(result["status"], "SENT")
        self.assertEqual(result["recipients"], 1)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.subject, "[Healthy] GX eTIMS Service | Health Check")
        self.assertIn("GX eTIMS SERVICE", email.body)
        self.assertEqual(email.alternatives[0][1], "text/html")
        self.assertIn("MADISON GROUP", email.alternatives[0][0])
        self.assertIn("Healthy &amp; Operational", email.alternatives[0][0])
        self.assertTrue(any(part.get("Content-ID") == "<madison-logo>" for part in email.attachments))
