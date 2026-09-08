"""Click + open tracking via the Mailgun webhook signal (Anymail's `tracking`)."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from anymail.signals import AnymailTrackingEvent
from newsletter.models import Newsletter, Subscription
from wagtail.rich_text import RichText

from prblm_mailer.models import Broadcast, EngagementEvent
from prblm_mailer.signals import handle_mailgun_event


def a_broadcast(**kw):
    data = {"subject": "Hi", "body": [("content", {"description": RichText("<p>x</p>")})]}
    data.update(kw)
    return Broadcast.objects.create(**data)


def fire(event_type, *, broadcast, subscription=None, recipient=None, url=None,
         event_id="evt1", ip="1.2.3.4", test=False):
    """Build a realistic Anymail tracking event and run it through the handler."""
    metadata = {"broadcast_id": str(broadcast.pk)}
    if subscription is not None:
        metadata["subscription_id"] = str(subscription.pk)
    if test:
        metadata["test"] = "1"
    event = AnymailTrackingEvent(
        event_type=event_type,
        timestamp=timezone.now(),
        recipient=recipient or (subscription.email_field if subscription else "x@x.co"),
        click_url=url,
        metadata=metadata,
        user_agent="UA",
        esp_event={"event-data": {"id": event_id, "ip": ip}},
    )
    handle_mailgun_event(sender=None, event=event, esp_name="Mailgun")


class EngagementTests(TestCase):
    def setUp(self):
        self.nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        self.sub = Subscription.objects.create(
            newsletter=self.nl, email_field="a@x.co", subscribed=True)
        self.b = a_broadcast(status=Broadcast.STATUS_SENT, emails_sent=10)

    def test_records_click_and_open(self):
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c1")
        fire("opened", broadcast=self.b, subscription=self.sub, event_id="o1")
        click = EngagementEvent.objects.get(kind=EngagementEvent.KIND_CLICK)
        self.assertEqual(click.subscription, self.sub)
        self.assertEqual(click.url, "https://ex.com/a")
        self.assertEqual(click.ip_address, "1.2.3.4")
        self.assertEqual(EngagementEvent.objects.filter(kind=EngagementEvent.KIND_OPEN).count(), 1)

    def test_dedupes_on_mailgun_event_id(self):
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="dup")
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="dup")
        self.assertEqual(EngagementEvent.objects.count(), 1)   # retry collapsed

    def test_email_fallback_attribution(self):
        # No subscription_id → resolve by recipient address, case-insensitively.
        fire("clicked", broadcast=self.b, recipient="A@X.CO", url="https://ex.com/a", event_id="c2")
        self.assertEqual(EngagementEvent.objects.get().subscription, self.sub)

    def test_test_send_is_ignored(self):
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", test=True)
        self.assertEqual(EngagementEvent.objects.count(), 0)

    def test_unsubscribe_click_excluded_from_stats(self):
        fire("clicked", broadcast=self.b, subscription=self.sub,
             url="https://site/mailer/unsubscribe/tok/", event_id="u1")
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c3")
        stats = self.b.engagement_stats()
        self.assertEqual(stats["clicks_total"], 1)     # the unsubscribe click doesn't count
        self.assertEqual(stats["clicks_unique"], 1)

    def test_stats_and_rate(self):
        sub2 = Subscription.objects.create(newsletter=self.nl, email_field="b@x.co", subscribed=True)
        fire("opened", broadcast=self.b, subscription=self.sub, event_id="o1")
        fire("opened", broadcast=self.b, subscription=sub2, event_id="o2")
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c1")
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c1b")
        stats = self.b.engagement_stats()
        self.assertEqual(stats["opens_unique"], 2)
        self.assertEqual(stats["open_rate"], 20.0)      # 2 unique / 10 sent
        self.assertEqual(stats["clicks_total"], 2)
        self.assertEqual(stats["clicks_unique"], 1)     # same person twice = one
        self.assertEqual(stats["click_rate"], 10.0)
        self.assertEqual(stats["top_urls"][0]["url"], "https://ex.com/a")

    def test_ip_scrubbed_and_unlinked_on_subscriber_delete(self):
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c1")
        self.sub.delete()
        event = EngagementEvent.objects.get()
        self.assertIsNone(event.ip_address)      # GDPR erasure
        self.assertIsNone(event.subscription)    # SET_NULL keeps the total accurate

    def test_clicks_and_opens_columns(self):
        fire("clicked", broadcast=self.b, subscription=self.sub, url="https://ex.com/a", event_id="c1")
        self.assertEqual(self.b.clicks_column(), 1)
        self.assertEqual(self.b.opens_column(), 0)
        draft = a_broadcast()                    # not sent → dash, never a number
        self.assertEqual(draft.clicks_column(), "—")


class SimulateCommandTests(TestCase):
    """The simulate_mailgun_click command drives the *real* webhook end to end:
    Anymail's signature check, its Mailgun payload parser, and our signal handler."""

    def setUp(self):
        self.nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        self.sub = Subscription.objects.create(
            newsletter=self.nl, email_field="a@x.co", subscribed=True)
        self.b = a_broadcast(status=Broadcast.STATUS_SENT, emails_sent=1)

    def test_simulate_records_a_click(self):
        out = StringIO()
        call_command("simulate_mailgun_click", stdout=out)
        self.assertEqual(EngagementEvent.objects.filter(kind=EngagementEvent.KIND_CLICK).count(), 1)
        self.assertIn("Click recorded", out.getvalue())

    def test_simulate_deduplicates_on_repeat_event_id(self):
        call_command("simulate_mailgun_click", "--event-id", "same", stdout=StringIO())
        out = StringIO()
        call_command("simulate_mailgun_click", "--event-id", "same", stdout=out)
        self.assertEqual(EngagementEvent.objects.count(), 1)   # retry didn't double-count
        self.assertIn("deduplicated", out.getvalue())
