"""CSV import/export of subscribers."""
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from newsletter.models import Newsletter, Subscription

from prblm_mailer.models import SubscriberTag
from prblm_mailer.segments import apply_tags


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class CsvTests(TestCase):
    def setUp(self):
        self.nl, _ = Newsletter.objects.get_or_create(
            slug="main", defaults={"title": "L", "email": "h@x.co", "sender": "X"})

    def _write_csv(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    # --- export ----------------------------------------------------------
    def test_export_writes_rows_with_groups(self):
        sub = Subscription.objects.create(
            newsletter=self.nl, email_field="a@x.co", name_field="Ann", subscribed=True)
        apply_tags(sub, [("Instrument", "Guitar")])
        path = self._write_csv("")
        call_command("export_subscribers", "--output", path)
        content = open(path).read()
        self.assertIn("email,name,status,groups", content)
        self.assertIn("a@x.co,Ann,confirmed,Instrument: Guitar", content)

    # --- import ----------------------------------------------------------
    def test_import_pending_by_default_and_applies_groups(self):
        path = self._write_csv(
            "email,name,groups\nnew@x.co,New Person,Instrument: Drums\n")
        call_command("import_subscribers", path, stdout=StringIO())
        sub = Subscription.objects.get(email_field="new@x.co")
        self.assertFalse(sub.subscribed)          # pending by default
        self.assertEqual(sub.name_field, "New Person")
        self.assertTrue(sub.tags.filter(group_name="Instrument", value_label="Drums").exists())

    def test_import_confirmed_flag(self):
        path = self._write_csv("email\nyes@x.co\n")
        call_command("import_subscribers", path, "--confirmed", stdout=StringIO())
        self.assertTrue(Subscription.objects.get(email_field="yes@x.co").subscribed)

    def test_import_skips_invalid_and_blank_emails(self):
        # A real row with an empty email cell (not a blank line, which DictReader drops).
        path = self._write_csv("email,name\ngood@x.co,G\nnotanemail,B\n,Blank\n")
        out = StringIO()
        call_command("import_subscribers", path, stdout=out)
        self.assertEqual(Subscription.objects.filter(newsletter=self.nl).count(), 1)
        self.assertIn("2 skipped", out.getvalue())

    def test_import_does_not_downgrade_confirmed_subscriber(self):
        Subscription.objects.create(newsletter=self.nl, email_field="c@x.co", subscribed=True)
        path = self._write_csv("email\nc@x.co\n")           # plain (pending) import
        call_command("import_subscribers", path, stdout=StringIO())
        self.assertTrue(Subscription.objects.get(email_field="c@x.co").subscribed)  # unchanged

    def test_round_trip(self):
        sub = Subscription.objects.create(
            newsletter=self.nl, email_field="r@x.co", name_field="R", subscribed=True)
        apply_tags(sub, [("Topic", "News")])
        export_path = self._write_csv("")
        call_command("export_subscribers", "--output", export_path)
        Subscription.objects.all().delete()
        SubscriberTag.objects.all().delete()
        call_command("import_subscribers", export_path, "--confirmed", stdout=StringIO())
        back = Subscription.objects.get(email_field="r@x.co")
        self.assertEqual(back.name_field, "R")
        self.assertTrue(back.tags.filter(group_name="Topic", value_label="News").exists())


class AdminCsvTests(TestCase):
    """The listing's Import/Export buttons — the same rules as the CLI commands."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from newsletter.models import Newsletter

        self.newsletter = Newsletter.objects.create(
            slug="main", title="L", email="h@x.co", sender="X")
        user = get_user_model().objects.create_superuser("admin2", "a2@b.co", "pw")
        self.client.force_login(user)

    def test_export_streams_a_csv_download(self):
        from newsletter.models import Subscription
        Subscription.objects.create(
            newsletter=self.newsletter, email_field="one@x.co", name_field="One")

        resp = self.client.get("/admin/subscribers/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment;", resp["Content-Disposition"])
        body = b"".join(resp.streaming_content).decode()
        self.assertIn("email,name,status", body)
        self.assertIn("one@x.co", body)

    def test_import_form_loads(self):
        resp = self.client.get("/admin/subscribers/import/")
        self.assertEqual(resp.status_code, 200)

    def test_import_defaults_to_pending(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from newsletter.models import Subscription

        csv_file = SimpleUploadedFile(
            "list.csv", b"email,name\npending@x.co,P\n", content_type="text/csv")
        resp = self.client.post("/admin/subscribers/import/", {"csv_file": csv_file})

        self.assertEqual(resp.status_code, 302)
        sub = Subscription.objects.get(email_field="pending@x.co")
        self.assertFalse(sub.subscribed)          # pending until they confirm

    def test_import_confirmed_when_declared(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from newsletter.models import Subscription

        csv_file = SimpleUploadedFile(
            "list.csv", b"email\nknown@x.co\n", content_type="text/csv")
        self.client.post(
            "/admin/subscribers/import/", {"csv_file": csv_file, "confirmed": "on"})

        self.assertTrue(Subscription.objects.get(email_field="known@x.co").subscribed)

    def test_import_sends_no_optin_email(self):
        from django.core import mail
        from django.core.files.uploadedfile import SimpleUploadedFile

        mail.outbox = []
        csv_file = SimpleUploadedFile(
            "list.csv", b"email\nquiet@x.co\n", content_type="text/csv")
        self.client.post("/admin/subscribers/import/", {"csv_file": csv_file})
        self.assertEqual(mail.outbox, [])

    def test_import_round_trips_an_export(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from newsletter.models import Subscription
        from prblm_mailer.segments import apply_tags

        sub = Subscription.objects.create(
            newsletter=self.newsletter, email_field="rt@x.co", name_field="RT")
        apply_tags(sub, [("Instrument", "Guitar")])

        exported = b"".join(
            self.client.get("/admin/subscribers/export/").streaming_content)
        Subscription.objects.all().delete()

        self.client.post("/admin/subscribers/import/", {
            "csv_file": SimpleUploadedFile("rt.csv", exported, content_type="text/csv")})

        restored = Subscription.objects.get(email_field="rt@x.co")
        self.assertEqual(restored.name_field, "RT")
        self.assertTrue(restored.tags.filter(value_label="Guitar").exists())

    def test_bad_upload_does_not_crash(self):
        resp = self.client.post("/admin/subscribers/import/", {})
        self.assertEqual(resp.status_code, 302)      # redirected with an error message
