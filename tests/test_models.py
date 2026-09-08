"""Phase 2: the models exist, migrate cleanly, and behave."""
from django.test import TestCase
from wagtail.rich_text import RichText  # Wagtail 6 needs a RichText, not a raw str

from prblm_mailer.models import Broadcast, EmailEvent, Subscriber, SubscriberTag


class BroadcastTests(TestCase):
    def make(self, **kw):
        data = {"subject": "Hi", "body": [("content", {"description": RichText("<p>x</p>")})]}
        data.update(kw)
        return Broadcast.objects.create(**data)

    def test_create_and_status(self):
        b = self.make()
        self.assertFalse(b.is_sent)
        self.assertEqual(b.status, Broadcast.STATUS_DRAFT)

    def test_duplicate_is_a_fresh_draft_carrying_groups(self):
        tag = SubscriberTag.objects.create(
            group_name="Interest", value_slug="c", value_label="contribute")
        b = self.make(status=Broadcast.STATUS_SENT, emails_sent=9)
        b.send_to_tags.add(tag)
        copy = b.duplicate()
        self.assertNotEqual(copy.pk, b.pk)
        self.assertEqual(copy.subject, "Hi (copy)")
        self.assertEqual(copy.status, Broadcast.STATUS_DRAFT)
        self.assertEqual(copy.emails_sent, 0)
        self.assertEqual(list(copy.send_to_tags.all()), [tag])

    def test_sent_audience_rows_parses(self):
        b = self.make(sent_audience="Interest: contribute, no group")
        rows = b.sent_audience_rows()
        self.assertEqual(rows[0], ("Interest", "contribute"))
        self.assertEqual(rows[1][0], "(no group)")

    def test_everyone_and_blank_give_no_rows(self):
        self.assertEqual(self.make(sent_audience="everyone").sent_audience_rows(), [])
        self.assertEqual(self.make(sent_audience="").sent_audience_rows(), [])


class SubscriberTagTests(TestCase):
    def test_pair_is_unique(self):
        from django.db import IntegrityError, transaction

        SubscriberTag.objects.create(group_name="G", value_slug="v", value_label="V")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriberTag.objects.create(group_name="G", value_slug="v", value_label="dup")


class SubscriberProxyTests(TestCase):
    def _sub(self, **kw):
        from newsletter.models import Newsletter, Subscription

        nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        return Subscription.objects.create(newsletter=nl, email_field="a@x.co", **kw)

    def test_status_reads_from_subscription(self):
        s = self._sub(subscribed=True)
        self.assertEqual(Subscriber.objects.get(pk=s.pk).status, "Confirmed")


class EmailEventTests(TestCase):
    def test_event_links_to_broadcast_nullably(self):
        b = Broadcast.objects.create(subject="s", body=[("content", {"description": RichText("<p>x</p>")})])
        e = EmailEvent.objects.create(email="a@x.co", event="bounced", broadcast=b)
        self.assertEqual(e.broadcast, b)
        b.delete()
        e.refresh_from_db()
        self.assertIsNone(e.broadcast)   # SET_NULL keeps the event
