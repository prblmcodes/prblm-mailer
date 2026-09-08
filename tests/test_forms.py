"""The optional form-builder helpers: NewsletterFormMixin + AbstractGroupingFormField.

Uses a concrete page (tests/testapp) built on the abstract bases, and drives a real
Wagtail form submission through it.
"""
from django.core import mail
from django.test import TestCase, override_settings

from newsletter.models import Newsletter, Subscription
from wagtail.models import Page

from prblm_mailer.models import SubscriberTag
from tests.testapp.models import GroupingFormField, NewsletterFormPage


@override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", "DELIVERY": "mailgun"})
class NewsletterFormPageTests(TestCase):
    def setUp(self):
        Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        root = Page.get_first_root_node()
        self.page = NewsletterFormPage(
            title="Signup", slug="signup",
            collect_newsletter_subscribers=True,
            to_address="owner@x.co", from_address="site@x.co", subject="New signup",
        )
        root.add_child(instance=self.page)
        GroupingFormField.objects.create(
            page=self.page, label="Email", field_type="email", required=True, sort_order=0)
        GroupingFormField.objects.create(
            page=self.page, label="Instrument", field_type="dropdown",
            choices="Guitar,Drums", use_for_grouping=True, sort_order=1)

    def _submit(self, data):
        form_class = self.page.get_form_class()
        form = form_class(data)
        assert form.is_valid(), form.errors
        return self.page.process_form_submission(form)

    def test_submission_subscribes_with_double_optin_and_groups(self):
        mail.outbox = []
        self._submit({"email": "new@x.co", "instrument": "Guitar"})

        sub = Subscription.objects.get(email_field="new@x.co")
        self.assertFalse(sub.subscribed)          # pending until they confirm
        self.assertTrue(sub.tags.filter(group_name="Instrument", value_label="Guitar").exists())
        # An opt-in email went out (plus the form's own notification to the owner).
        self.assertTrue(any("new@x.co" in m.to for m in mail.outbox))

    def test_toggle_off_does_not_subscribe(self):
        self.page.collect_newsletter_subscribers = False
        self.page.save()
        self._submit({"email": "nope@x.co", "instrument": "Drums"})
        self.assertFalse(Subscription.objects.filter(email_field="nope@x.co").exists())

    def test_resolved_group_name_falls_back_to_label(self):
        field = GroupingFormField.objects.get(label="Instrument")
        self.assertEqual(field.resolved_group_name, "Instrument")     # no explicit group_name
        field.group_name = "Plays"
        self.assertEqual(field.resolved_group_name, "Plays")          # explicit wins

    def test_grouping_tag_is_shared_not_duplicated(self):
        self._submit({"email": "a@x.co", "instrument": "Guitar"})
        self._submit({"email": "b@x.co", "instrument": "Guitar"})
        self.assertEqual(
            SubscriberTag.objects.filter(group_name="Instrument", value_slug="guitar").count(), 1)

    def test_free_text_field_cannot_be_marked_for_grouping(self):
        from django.core.exceptions import ValidationError
        field = GroupingFormField(
            page=self.page, label="Comments", field_type="singleline",
            use_for_grouping=True, sort_order=9)
        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_grouping_ignores_non_choice_field_at_submission(self):
        # Even if a text field is flagged (bypassing the editor), it makes no groups.
        from prblm_mailer.segments import grouping_specs
        GroupingFormField.objects.create(
            page=self.page, label="Comments", field_type="singleline",
            use_for_grouping=True, sort_order=9)
        groups = [g for _, g in grouping_specs(self.page)]
        self.assertIn("Instrument", groups)        # the dropdown is kept
        self.assertNotIn("Comments", groups)       # the text field is skipped


@override_settings(PRBLM_MAILER={"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", "DELIVERY": "mailgun"})
class OptInFieldTests(TestCase):
    """A form whose newsletter signup is conditional on a consent checkbox."""

    def setUp(self):
        Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})
        root = Page.get_first_root_node()
        self.page = NewsletterFormPage(
            title="Contact", slug="contact",
            collect_newsletter_subscribers=True,
            to_address="owner@x.co", from_address="site@x.co", subject="New message",
        )
        root.add_child(instance=self.page)
        GroupingFormField.objects.create(
            page=self.page, label="Email", field_type="email", required=True, sort_order=0)
        GroupingFormField.objects.create(
            page=self.page, label="Keep me posted", field_type="checkbox",
            required=False, use_for_optin=True, sort_order=1)

    def _submit(self, data):
        form_class = self.page.get_form_class()
        form = form_class(data)
        assert form.is_valid(), form.errors
        return self.page.process_form_submission(form)

    def test_ticked_subscribes(self):
        self._submit({"email": "yes@x.co", "keep_me_posted": True})
        self.assertTrue(Subscription.objects.filter(email_field="yes@x.co").exists())

    def test_unticked_does_not_subscribe(self):
        submission = self._submit({"email": "no@x.co", "keep_me_posted": False})
        self.assertFalse(Subscription.objects.filter(email_field="no@x.co").exists())
        # The form itself is unaffected — only the list is skipped.
        self.assertIsNotNone(submission)

    def test_unticked_sends_no_optin_email(self):
        mail.outbox = []
        self._submit({"email": "quiet@x.co", "keep_me_posted": False})
        self.assertFalse(any("quiet@x.co" in m.to for m in mail.outbox))

    def test_missing_answer_counts_as_declined(self):
        # Silence is not consent: a marked field absent from cleaned_data must not subscribe.
        from prblm_mailer.subscriptions import subscribe_from_form
        self.assertIsNone(subscribe_from_form({"email": "absent@x.co"}, page=self.page))
        self.assertFalse(Subscription.objects.filter(email_field="absent@x.co").exists())

    def test_page_without_optin_field_subscribes_everyone(self):
        # Existing forms must be unaffected by the feature.
        plain = NewsletterFormPage(
            title="Plain", slug="plain", collect_newsletter_subscribers=True,
            to_address="owner@x.co", from_address="site@x.co", subject="s",
        )
        Page.get_first_root_node().add_child(instance=plain)
        GroupingFormField.objects.create(
            page=plain, label="Email", field_type="email", required=True, sort_order=0)
        form_class = plain.get_form_class()
        form = form_class({"email": "everyone@x.co"})
        assert form.is_valid(), form.errors
        plain.process_form_submission(form)
        self.assertTrue(Subscription.objects.filter(email_field="everyone@x.co").exists())

    def test_optin_must_be_a_checkbox(self):
        from django.core.exceptions import ValidationError
        field = GroupingFormField(
            page=self.page, label="Comments", field_type="singleline",
            use_for_optin=True, sort_order=9)
        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_non_checkbox_flagged_field_is_ignored_at_submission(self):
        # Flagged some other way (bypassing the editor) it must not gate anything.
        from prblm_mailer.segments import optin_field_name
        GroupingFormField.objects.all().filter(label="Keep me posted").delete()
        GroupingFormField.objects.create(
            page=self.page, label="Comments", field_type="singleline",
            use_for_optin=True, sort_order=9)
        self.assertIsNone(optin_field_name(self.page))
