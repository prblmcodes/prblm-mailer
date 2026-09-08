"""List hygiene: hard bounces / complaints auto-unsubscribe; soft bounces don't."""
from django.test import TestCase
from django.utils import timezone

from anymail.signals import AnymailTrackingEvent
from newsletter.models import Newsletter, Subscription

from prblm_mailer.models import EmailEvent
from prblm_mailer.signals import handle_mailgun_event


def bounce(event_type, recipient):
    event = AnymailTrackingEvent(
        event_type=event_type,
        timestamp=timezone.now(),
        recipient=recipient,
        description="mailbox does not exist",
        esp_event={"event-data": {"id": "e1"}},
    )
    handle_mailgun_event(sender=None, event=event, esp_name="Mailgun")


class HygieneTests(TestCase):
    def setUp(self):
        self.nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        self.sub = Subscription.objects.create(
            newsletter=self.nl, email_field="a@x.co", subscribed=True)

    def test_hard_bounce_unsubscribes(self):
        bounce("bounced", "a@x.co")
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.unsubscribed)
        self.assertFalse(self.sub.subscribed)
        self.assertTrue(EmailEvent.objects.filter(email="a@x.co", event="bounced").exists())

    def test_complaint_unsubscribes_case_insensitively(self):
        bounce("complained", "A@X.CO")          # Mailgun may report a different case
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.unsubscribed)

    def test_soft_bounce_does_not_unsubscribe(self):
        bounce("deferred", "a@x.co")            # not a hard event
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.unsubscribed)
        self.assertTrue(self.sub.subscribed)
