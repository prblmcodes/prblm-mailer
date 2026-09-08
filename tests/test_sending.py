"""Phase 3: the sending engine — render, DRY_RUN, opt-in, unsubscribe."""
from unittest import mock

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from newsletter.models import Newsletter, Subscription
from wagtail.rich_text import RichText  # Wagtail 6 needs a RichText, not a raw str

from prblm_mailer import sending
from prblm_mailer.conf import get_setting
from prblm_mailer.models import Broadcast
from prblm_mailer.subscriptions import confirmed_subscriptions, subscribe_from_form
from prblm_mailer.tokens import oneclick_token


def _locmem():
    """A local in-memory mail connection, so console/local sends land in outbox."""
    return mail.get_connection("django.core.mail.backends.locmem.EmailBackend")


def a_newsletter():
    nl, _ = Newsletter.objects.get_or_create(
        slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
    return nl


def a_broadcast(**kw):
    data = {"subject": "Hi", "body": [
        ("content", {"heading": "Hello", "description": RichText("<p>Body</p>")}),
        ("footer", {"show_unsubscribe": True}),
    ]}
    data.update(kw)
    return Broadcast.objects.create(**data)


class RenderTests(TestCase):
    def test_body_compiles_to_email_html(self):
        html = sending.render_email_html(a_broadcast())
        self.assertIn("<table", html)          # MJML compiled
        self.assertNotIn("<mjml", html)
        self.assertIn("Hello", html)
        self.assertIn("%recipient.unsubscribe_url%", html)   # footer merge tag survives

    def test_render_needs_no_host_app(self):
        # Renders with no SiteConfig / core import — the footer is the Footer block,
        # authored per-newsletter, not pulled from a host model.
        html = sending.render_email_html(a_broadcast())
        self.assertIn("Unsubscribe", html)      # the Footer block rendered


class DryRunTests(TestCase):
    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DRY_RUN": True})
    def test_dry_run_does_not_send_but_marks_sent(self):
        nl = a_newsletter()
        Subscription.objects.create(newsletter=nl, email_field="a@x.co", subscribed=True)
        b = a_broadcast()
        mail.outbox = []
        with self.assertLogs("prblm_mailer.sending", level="INFO") as logs:
            sending.send_broadcast(b.pk)
        b.refresh_from_db()
        self.assertEqual(mail.outbox, [])       # nothing sent
        self.assertTrue(b.is_sent)              # but recorded
        self.assertEqual(b.emails_sent, 1)
        self.assertTrue(any("DRY_RUN" in m for m in logs.output))

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DRY_RUN": False})
    def test_real_send_builds_a_message_with_merge_data(self):
        nl = a_newsletter()
        Subscription.objects.create(newsletter=nl, email_field="a@x.co", subscribed=True)
        b = a_broadcast()
        mail.outbox = []
        sending.send_broadcast(b.pk)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn("a@x.co", sent.merge_data)                 # per-recipient vars
        self.assertIn("a@x.co", sent.merge_metadata)             # subscription_id
        self.assertEqual(sent.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")


class DeliveryModeTests(TestCase):
    """The four-mode DELIVERY switch and its local (console/inbox) path."""

    def test_delivery_defaults_from_dry_run(self):
        with override_settings(PRBLM_MAILER={"DRY_RUN": True}):
            self.assertEqual(get_setting("DELIVERY"), "dry_run")
        with override_settings(PRBLM_MAILER={"DRY_RUN": False}):
            self.assertEqual(get_setting("DELIVERY"), "mailgun")

    def test_explicit_delivery_wins(self):
        with override_settings(PRBLM_MAILER={"DRY_RUN": True, "DELIVERY": "console"}):
            self.assertEqual(get_setting("DELIVERY"), "console")

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DELIVERY": "bogus"})
    def test_invalid_delivery_mode_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            sending.send_broadcast(a_broadcast().pk)

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DELIVERY": "console"})
    def test_local_mode_sends_one_personalized_email_per_recipient(self):
        nl = a_newsletter()
        Subscription.objects.create(newsletter=nl, email_field="a@x.co", subscribed=True)
        Subscription.objects.create(newsletter=nl, email_field="b@x.co", subscribed=True)
        b = a_broadcast()
        mail.outbox = []
        with mock.patch.object(sending, "_local_connection", return_value=_locmem()):
            sending.send_broadcast(b.pk)

        self.assertEqual(len(mail.outbox), 2)             # one per recipient, not a batch
        addresses = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(addresses, ["a@x.co", "b@x.co"])

        body = mail.outbox[0].alternatives[0][0]          # the HTML part
        self.assertNotIn("%recipient.", body)             # placeholders substituted
        self.assertIn("/newsletter/main/subscription/", body)   # real per-recipient unsub link
        header = mail.outbox[0].extra_headers             # one-click header filled in
        self.assertIn("/mailer/unsubscribe/", header["List-Unsubscribe"])
        self.assertNotIn("%recipient.", header["List-Unsubscribe"])
        self.assertEqual(header["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        b.refresh_from_db()
        self.assertTrue(b.is_sent)
        self.assertEqual(b.emails_sent, 2)

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DELIVERY": "console"})
    def test_test_send_local_is_personalized(self):
        mail.outbox = []
        with mock.patch.object(sending, "_local_connection", return_value=_locmem()):
            sending.send_test(a_broadcast(), "me@x.co")
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("%recipient.", mail.outbox[0].alternatives[0][0])

    def test_local_delivery_reports_unreachable_inbox(self):
        # Nothing is listening on this port → a clear, actionable error (mailcrab hint).
        with override_settings(PRBLM_MAILER={"LOCAL_SMTP_HOST": "127.0.0.1",
                                             "LOCAL_SMTP_PORT": 1}):
            with self.assertRaises(RuntimeError) as ctx:
                sending._local_connection("local")
        self.assertIn("mailcrab", str(ctx.exception))


class OptInTests(TestCase):
    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", "DELIVERY": "mailgun"})
    def test_signup_creates_pending_and_sends_optin(self):
        a_newsletter()
        mail.outbox = []
        sub = subscribe_from_form({"email": "new@x.co"})
        self.assertIsNotNone(sub)
        self.assertFalse(sub.subscribed)         # pending until confirmed
        self.assertEqual(len(mail.outbox), 1)    # opt-in email (DELIVERY sends it)
        self.assertIn("new@x.co", mail.outbox[0].to)
        self.assertNotIn(sub, confirmed_subscriptions())

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", "DELIVERY": "dry_run"})
    def test_optin_honours_dry_run(self):
        a_newsletter()
        mail.outbox = []
        with self.assertLogs("prblm_mailer.sending", level="INFO") as logs:
            sub = subscribe_from_form({"email": "new@x.co"})
        self.assertIsNotNone(sub)
        self.assertFalse(sub.subscribed)         # still created pending
        self.assertEqual(mail.outbox, [])        # but nothing sent under dry_run
        self.assertTrue(any("opt-in" in m for m in logs.output))

    @override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X"})
    def test_confirmed_subscriber_is_reachable(self):
        nl = a_newsletter()
        Subscription.objects.create(newsletter=nl, email_field="c@x.co", subscribed=True)
        self.assertEqual([s.email for s in confirmed_subscriptions()], ["c@x.co"])


class UnsubscribeTests(TestCase):
    def setUp(self):
        self.nl = a_newsletter()
        self.sub = Subscription.objects.create(
            newsletter=self.nl, email_field="u@x.co", subscribed=True)
        self.url = reverse("prblm_mailer:oneclick_unsubscribe",
                           args=[oneclick_token(self.sub)])

    def test_get_shows_confirm_and_does_not_unsubscribe(self):
        resp = self.client.get(self.url)
        self.sub.refresh_from_db()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.sub.unsubscribed)
        self.assertIn("Unsubscribe from this newsletter?", resp.content.decode())

    def test_post_unsubscribes(self):
        self.client.post(self.url)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.unsubscribed)

    def test_tampered_token_rejected(self):
        bad = reverse("prblm_mailer:oneclick_unsubscribe", args=["garbage"])
        self.assertEqual(self.client.post(bad).status_code, 400)
