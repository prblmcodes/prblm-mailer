"""django-newsletter's public pages: mounted, reachable, and wearing our styling."""
from django.test import TestCase, override_settings
from django.urls import reverse

from newsletter.models import Newsletter, Subscription

from prblm_mailer.checks import check_prblm_mailer_settings


@override_settings(PRBLM_MAILER={
    "FROM_EMAIL": "hi@x.co", "FROM_NAME": "The Sender", "BRAND_COLOR": "#abcdef",
})
class PublicPageStylingTests(TestCase):
    def setUp(self):
        self.newsletter = Newsletter.objects.create(
            slug="main", title="The List", email="h@x.co", sender="X")
        from django.contrib.sites.models import Site
        self.newsletter.site.add(Site.objects.get_current())

    def test_unsubscribe_page_uses_the_styled_shell(self):
        resp = self.client.get("/newsletter/main/unsubscribe/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "card__body")       # our shell, not the bare default
        self.assertContains(resp, "#abcdef")          # brand colour reached the page
        self.assertContains(resp, "The Sender")       # footer identity

    def test_subscribe_page_is_styled(self):
        resp = self.client.get("/newsletter/main/subscribe/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "card__body")

    def test_activation_completed_page_exists(self):
        # The page the activation link redirects to — a 404 here is the URL-ordering bug.
        resp = self.client.get("/newsletter/main/subscribe/activation-completed/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "card__body")

    def test_email_sent_page_exists(self):
        resp = self.client.get("/newsletter/main/subscribe/email-sent/")
        self.assertEqual(resp.status_code, 200)

    def test_unsubscribe_activation_completed_page_exists(self):
        resp = self.client.get("/newsletter/main/unsubscribe/activation-completed/")
        self.assertEqual(resp.status_code, 200)

    def test_activate_page_renders_for_a_real_subscription(self):
        sub = Subscription.objects.create(
            newsletter=self.newsletter, email_field="who@x.co")
        resp = self.client.get(sub.subscribe_activate_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "card__body")

    def test_host_can_still_override_the_shell(self):
        # Nothing here is forced: the shell is a plain template, resolved normally.
        from django.template.loader import get_template
        tpl = get_template("newsletter/common.html")
        self.assertIn("prblm_mailer", tpl.template.origin.name)


class UrlOrderingCheckTests(TestCase):
    def test_no_warning_when_newsletter_urls_answer(self):
        ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertNotIn("prblm_mailer.W004", ids)

    @override_settings(ROOT_URLCONF="tests.urls_shadowed")
    def test_warns_when_wagtail_catch_all_shadows_them(self):
        ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertIn("prblm_mailer.W004", ids)

@override_settings(PRBLM_MAILER={
    "FROM_EMAIL": "hi@x.co", "FROM_NAME": "The Sender", "BRAND_COLOR": "#abcdef",
})
class ActivatePageTests(TestCase):
    """The page the confirmation link lands on."""

    def setUp(self):
        from django.contrib.sites.models import Site
        self.newsletter = Newsletter.objects.create(
            slug="main", title="The List", email="h@x.co", sender="X")
        self.newsletter.site.add(Site.objects.get_current())
        self.sub = Subscription.objects.create(
            newsletter=self.newsletter, email_field="who@x.co")

    def test_activation_code_is_not_shown_in_a_text_box(self):
        resp = self.client.get(self.sub.subscribe_activate_url())
        html = resp.content.decode()
        self.assertIn('type="hidden"', html)
        self.assertNotIn('type="text" name="user_activation_code"', html)
        # The code still travels with the form, so confirming works.
        self.assertIn(self.sub.activation_code, html)

    def test_confirming_still_works(self):
        url = self.sub.subscribe_activate_url()
        resp = self.client.post(url, {"user_activation_code": self.sub.activation_code})
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.subscribed)

    def test_already_confirmed_link_says_so_instead_of_reoffering(self):
        Subscription.objects.filter(pk=self.sub.pk).update(subscribed=True)
        resp = self.client.get(self.sub.subscribe_activate_url())
        self.assertContains(resp, "Already confirmed")
        self.assertNotContains(resp, "Confirm subscription</button>")

    def test_pending_signup_offers_deny(self):
        resp = self.client.get(self.sub.subscribe_activate_url())
        self.assertContains(resp, "Deny subscription")
        self.assertContains(resp, reverse("prblm_mailer:deny_subscription"))

    def test_deny_removes_the_pending_subscription(self):
        resp = self.client.post(reverse("prblm_mailer:deny_subscription"), {
            "email": self.sub.email_field, "code": self.sub.activation_code})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "you won't be subscribed")
        self.assertFalse(Subscription.objects.filter(pk=self.sub.pk).exists())

    def test_deny_cannot_remove_a_confirmed_subscriber(self):
        Subscription.objects.filter(pk=self.sub.pk).update(subscribed=True)
        self.sub.refresh_from_db()
        self.client.post(reverse("prblm_mailer:deny_subscription"), {
            "email": self.sub.email_field, "code": self.sub.activation_code})
        self.assertTrue(Subscription.objects.filter(pk=self.sub.pk).exists())

    def test_unsubscribe_link_shows_the_unsubscribe_wording(self):
        Subscription.objects.filter(pk=self.sub.pk).update(subscribed=True)
        self.sub.refresh_from_db()
        resp = self.client.get(self.sub.unsubscribe_activate_url())
        self.assertContains(resp, "Yes, unsubscribe me")
        self.assertNotContains(resp, "Deny subscription")

    def test_already_unsubscribed_link_says_so(self):
        Subscription.objects.filter(pk=self.sub.pk).update(unsubscribed=True)
        self.sub.refresh_from_db()
        resp = self.client.get(self.sub.unsubscribe_activate_url())
        self.assertContains(resp, "Already unsubscribed")
