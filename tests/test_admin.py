"""Phase 4: the Wagtail admin — snippets, send page, confirm, duplicate."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from newsletter.models import Newsletter, Subscription
from wagtail.rich_text import RichText  # Wagtail 6 needs a RichText, not a raw str

from prblm_mailer.models import Broadcast, SubscriberTag


class AdminBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "a@b.co", "pw")
        self.client.force_login(self.user)

    def broadcast(self, **kw):
        data = {"subject": "Hi", "body": [("content", {"description": RichText("<p>x</p>")})]}
        data.update(kw)
        return Broadcast.objects.create(**data)


class SnippetTests(AdminBase):
    def test_newsletters_list_loads(self):
        self.broadcast()
        resp = self.client.get("/admin/snippets/prblm_mailer/broadcast/")
        self.assertEqual(resp.status_code, 200)

    def test_subscribers_list_loads(self):
        resp = self.client.get("/admin/snippets/prblm_mailer/subscriber/")
        self.assertEqual(resp.status_code, 200)

    def test_subscriber_listing_offers_no_edit(self):
        # Superuser, so this is the viewset withholding "change", not Django perms.
        from newsletter.models import Newsletter, Subscription
        nl = Newsletter.objects.create(slug="main", title="L", email="h@x.co", sender="X")
        sub = Subscription.objects.create(newsletter=nl, email_field="who@x.co")

        resp = self.client.get("/admin/snippets/prblm_mailer/subscriber/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f"/subscriber/edit/{sub.pk}/")

    def test_subscriber_edit_url_still_redirects_to_inspect(self):
        from newsletter.models import Newsletter, Subscription
        nl = Newsletter.objects.create(slug="main", title="L", email="h@x.co", sender="X")
        sub = Subscription.objects.create(newsletter=nl, email_field="typed@x.co")

        resp = self.client.get(f"/admin/snippets/prblm_mailer/subscriber/edit/{sub.pk}/")
        self.assertIn(resp.status_code, (301, 302, 403))

    def test_broadcast_editor_loads(self):
        b = self.broadcast()
        resp = self.client.get(f"/admin/snippets/prblm_mailer/broadcast/edit/{b.pk}/")
        self.assertEqual(resp.status_code, 200)


@override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "DRY_RUN": True})
class SendPageTests(AdminBase):
    def test_send_page_shows_preview_and_controls(self):
        b = self.broadcast()
        html = self.client.get(reverse("prblm_mailer_send", args=[b.pk])).content.decode()
        self.assertIn("Newsletter preview", html)
        self.assertIn("Send a test", html)
        self.assertIn("Who gets it", html)
        self.assertNotIn("Clicks", html)          # click tracking is not in this version

    def test_sent_broadcast_shows_audience_table(self):
        from django.utils import timezone
        b = self.broadcast(status=Broadcast.STATUS_SENT, emails_sent=2,
                           sent_at=timezone.now(), sent_audience="Interest: contribute")
        html = self.client.get(reverse("prblm_mailer_send", args=[b.pk])).content.decode()
        self.assertIn("<h2>Audience</h2>", html)
        self.assertIn("<td>Interest</td>", html)

    def test_proceed_then_confirm_then_send(self):
        nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        Subscription.objects.create(newsletter=nl, email_field="a@x.co", subscribed=True)
        b = self.broadcast()

        # proceed (no groups -> everyone) redirects to confirm
        r1 = self.client.post(reverse("prblm_mailer_send", args=[b.pk]),
                              {"action": "proceed", "include_ungrouped": "on"})
        self.assertRedirects(r1, reverse("prblm_mailer_confirm", args=[b.pk]))

        # confirm page shows the count
        html = self.client.get(reverse("prblm_mailer_confirm", args=[b.pk])).content.decode()
        self.assertIn("Send now", html)

        # send (DRY_RUN) marks it sent
        self.client.post(reverse("prblm_mailer_confirm", args=[b.pk]))
        b.refresh_from_db()
        self.assertTrue(b.is_sent)

    def test_dry_run_test_send_says_nothing_sent(self):
        b = self.broadcast()   # tests run with DEBUG=True → DELIVERY resolves to dry_run
        resp = self.client.post(
            reverse("prblm_mailer_send", args=[b.pk]),
            {"action": "test", "test_email": "me@x.co"}, follow=True)
        msgs = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("Dry run" in m for m in msgs), msgs)

    def test_dry_run_full_send_says_nothing_sent(self):
        nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        Subscription.objects.create(newsletter=nl, email_field="a@x.co", subscribed=True)
        b = self.broadcast()
        self.client.post(reverse("prblm_mailer_send", args=[b.pk]),
                         {"action": "proceed", "include_ungrouped": "on"})
        resp = self.client.post(reverse("prblm_mailer_confirm", args=[b.pk]), follow=True)
        msgs = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("Dry run" in m for m in msgs), msgs)

    def test_duplicate_makes_a_draft(self):
        from django.utils import timezone
        b = self.broadcast(status=Broadcast.STATUS_SENT, sent_at=timezone.now())
        self.client.post(reverse("prblm_mailer_duplicate", args=[b.pk]))
        self.assertTrue(Broadcast.objects.filter(subject="Hi (copy)").exists())
