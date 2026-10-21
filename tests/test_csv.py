"""CSV import/export of subscribers."""
import datetime
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

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

    # The import is two steps now: upload, then confirm the columns. These helpers
    # keep the tests about behaviour rather than about posting forms twice.
    def upload(self, body, name="list.csv"):
        """Step one. Returns the mapping page's response."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post("/admin/subscribers/import/", {
            "csv_file": SimpleUploadedFile(name, body, content_type="text/csv")})

    def commit(self, page, mapping=None, confirmed=False):
        """Step two: import what step one parked, optionally overriding columns."""
        data = {"token": page.context["token"], "action": "import"}
        data.update({f"map_{k}": v for k, v in (mapping or page.context["mapping"]).items() if v})
        if confirmed:
            data["confirmed"] = "on"
        return self.client.post("/admin/subscribers/import/", data)

    def test_upload_shows_the_mapping_screen_without_importing(self):
        from newsletter.models import Subscription

        page = self.upload(b"email,name\npending@x.co,P\n")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["mapping"]["email"], "email")
        self.assertEqual(page.context["preview"].created, 1)
        self.assertFalse(Subscription.objects.exists())     # nothing written yet

    def test_import_defaults_to_pending(self):
        from newsletter.models import Subscription

        resp = self.commit(self.upload(b"email,name\npending@x.co,P\n"))

        self.assertEqual(resp.status_code, 302)
        sub = Subscription.objects.get(email_field="pending@x.co")
        self.assertFalse(sub.subscribed)          # pending until they confirm

    def test_import_confirmed_when_declared(self):
        from newsletter.models import Subscription

        self.commit(self.upload(b"email\nknown@x.co\n"), confirmed=True)

        self.assertTrue(Subscription.objects.get(email_field="known@x.co").subscribed)

    def test_an_unrecognised_header_is_detected_and_imported(self):
        # The real failing case: 686 rows under a column called "Subscriber".
        from newsletter.models import Subscription

        page = self.upload(
            b"Subscriber,Sent,Opens,Clicks,Subscribed,Location\n"
            b'claire.reed@essex.gov.uk,0,0,0,"2025-09-17 07:16:57",\n'
            b'sarah@srowell.co.uk,0,0,0,"2025-09-09 08:37:48",\n')
        self.assertEqual(page.context["mapping"]["email"], "Subscriber")

        self.commit(page)
        self.assertEqual(Subscription.objects.count(), 2)

    def test_the_mapping_can_be_overridden(self):
        from newsletter.models import Subscription

        page = self.upload(b"primary,secondary\na@x.co,b@x.co\n")
        self.commit(page, mapping={"email": "secondary"})
        self.assertEqual(
            set(Subscription.objects.values_list("email_field", flat=True)), {"b@x.co"})

    def test_a_file_with_no_email_column_says_so_instead_of_importing_nothing(self):
        page = self.upload(b"Sent,Opens\n0,0\n1,2\n")
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context["mapping"]["email"])
        self.assertContains(page, "Couldn't tell which column")

    def test_an_expired_upload_asks_for_the_file_again(self):
        resp = self.client.post("/admin/subscribers/import/", {
            "token": "x" * 24, "action": "import"})
        self.assertEqual(resp.status_code, 302)

    def test_import_sends_no_optin_email(self):
        from django.core import mail

        mail.outbox = []
        self.commit(self.upload(b"email\nquiet@x.co\n"))
        self.assertEqual(mail.outbox, [])

    def test_import_round_trips_an_export(self):
        from newsletter.models import Subscription
        from prblm_mailer.segments import apply_tags

        sub = Subscription.objects.create(
            newsletter=self.newsletter, email_field="rt@x.co", name_field="RT")
        apply_tags(sub, [("Instrument", "Guitar")])

        exported = b"".join(
            self.client.get("/admin/subscribers/export/").streaming_content)
        Subscription.objects.all().delete()

        self.commit(self.upload(exported, name="rt.csv"))

        restored = Subscription.objects.get(email_field="rt@x.co")
        self.assertEqual(restored.name_field, "RT")
        self.assertTrue(restored.tags.filter(value_label="Guitar").exists())

    def test_bad_upload_does_not_crash(self):
        resp = self.client.post("/admin/subscribers/import/", {})
        self.assertEqual(resp.status_code, 302)      # redirected with an error message


class ColumnDetectionTests(SimpleTestCase):
    """Finding the columns in a CSV from anywhere. No database needed."""

    def detect(self, text):
        from prblm_mailer.csv_io import detect_columns, read_table

        headers, rows = read_table(text)
        return detect_columns(headers, rows), headers, rows

    def test_the_plugins_own_export_is_recognised(self):
        mapping, headers, rows = self.detect(
            "email,name,status,groups,subscribe_date,create_date\n"
            "a@x.co,Ann,confirmed,Instrument: Guitar,2025-01-01,2025-01-01\n")
        self.assertEqual(mapping["email"], "email")
        self.assertEqual(mapping["name"], "name")
        self.assertEqual(mapping["groups"], "groups")
        self.assertEqual(len(rows), 1)

    def test_groups_with_semicolons_do_not_fool_the_delimiter_sniffer(self):
        _, headers, rows = self.detect(
            'email,name,groups\n'
            'a@x.co,Ann,"Instrument: Guitar; City: Leeds"\n')
        self.assertEqual(headers, ["email", "name", "groups"])
        self.assertEqual(rows[0]["groups"], "Instrument: Guitar; City: Leeds")

    def test_the_real_file_that_imported_nothing(self):
        # 686 rows arrived under a column called "Subscriber" and every one was
        # skipped. "Subscribed" here is a date, not a status — it must not be read
        # as one, or every row would look opted out.
        mapping, _, _ = self.detect(
            "Subscriber,Sent,Opens,Clicks,Subscribed,Location\n"
            'claire.reed@essex.gov.uk,0,0,0,"2025-09-17 07:16:57",\n'
            'sarah@srowell.co.uk,0,0,0,"2025-09-09 08:37:48",\n')
        self.assertEqual(mapping["email"], "Subscriber")
        self.assertIsNone(mapping["status"])

    def test_mailchimp_style_header(self):
        mapping, _, _ = self.detect(
            "Email Address,First Name,Last Name,Status\n"
            "a@x.co,Ann,Smith,subscribed\n")
        self.assertEqual(mapping["email"], "Email Address")
        self.assertEqual(mapping["first_name"], "First Name")
        self.assertEqual(mapping["last_name"], "Last Name")
        self.assertEqual(mapping["status"], "Status")

    def test_an_unknown_header_is_found_by_its_values(self):
        mapping, _, _ = self.detect(
            "Contact Details,Sent\n" + "".join(f"user{i}@x.co,0\n" for i in range(10)))
        self.assertEqual(mapping["email"], "Contact Details")

    def test_a_column_with_only_the_odd_address_is_not_chosen(self):
        mapping, _, _ = self.detect(
            "Notes,Sent\n" + "a@x.co,0\n" + "".join(f"note {i},0\n" for i in range(10)))
        self.assertIsNone(mapping["email"])

    def test_semicolon_and_tab_delimited_files(self):
        for text in ("Email Address;Name\na@x.co;Ann\nb@x.co;Bob\n",
                     "Email Address\tName\na@x.co\tAnn\nb@x.co\tBob\n"):
            with self.subTest(text=text[:20]):
                mapping, _, rows = self.detect(text)
                self.assertEqual(mapping["email"], "Email Address")
                self.assertEqual(len(rows), 2)

    def test_a_headerless_file_keeps_every_row(self):
        mapping, headers, rows = self.detect("a@x.co\nb@x.co\nc@x.co\n")
        self.assertEqual(len(rows), 3)
        self.assertEqual(headers, ["Column 1"])
        self.assertEqual(mapping["email"], "Column 1")

    def test_a_ragged_row_does_not_shift_later_columns(self):
        _, _, rows = self.detect("email,name,groups\na@x.co,Ann\n")
        self.assertEqual(rows[0]["name"], "Ann")
        self.assertEqual(rows[0]["groups"], "")


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class ImportRowsTests(TestCase):
    """What the importer does with the rows it finds."""

    def setUp(self):
        from newsletter.models import Newsletter

        self.newsletter = Newsletter.objects.create(
            slug="main", title="L", email="h@x.co", sender="X")

    def run_import(self, text, **kw):
        from prblm_mailer.csv_io import import_rows

        return import_rows(text, self.newsletter, **kw)

    def emails(self):
        from newsletter.models import Subscription

        return set(Subscription.objects.values_list("email_field", flat=True))

    def test_a_file_with_no_email_column_says_so(self):
        from prblm_mailer.csv_io import NoEmailColumn

        with self.assertRaises(NoEmailColumn) as caught:
            self.run_import("Sent,Opens\n0,0\n1,2\n")
        self.assertIn("Sent", str(caught.exception))      # names what it did see

    def test_the_old_four_value_unpacking_still_works(self):
        created, updated, skipped, bad = self.run_import("email\na@x.co\n")
        self.assertEqual((created, updated, skipped, bad), (1, 0, 0, []))

    def test_counts_are_broken_down_by_reason(self):
        result = self.run_import(
            "Email Address,Status\n"
            "a@x.co,subscribed\n"
            "b@x.co,unsubscribed\n"      # opted out elsewhere
            "a@x.co,subscribed\n"        # repeat of the first row
            "not-an-email,subscribed\n")
        self.assertEqual(result.created, 1)
        self.assertEqual(result.opted_out, 1)
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(result.invalid, 1)
        self.assertEqual(result.skipped, 3)
        self.assertEqual(self.emails(), {"a@x.co"})

    def test_people_who_opted_out_elsewhere_are_never_added(self):
        self.run_import("email,status\ngone@x.co,unsubscribed\ngone2@x.co,cleaned\n")
        self.assertEqual(self.emails(), set())

    def test_addresses_are_trimmed_and_lowercased(self):
        self.run_import("email\n  Ann@Example.CO  \n")
        self.assertEqual(self.emails(), {"ann@example.co"})

    def test_an_existing_subscriber_is_matched_whatever_the_case(self):
        from newsletter.models import Subscription

        Subscription.objects.create(newsletter=self.newsletter, email_field="ann@x.co")
        result = self.run_import("email\nANN@x.co\n")
        self.assertEqual((result.created, result.updated), (0, 1))
        self.assertEqual(Subscription.objects.count(), 1)

    def test_first_and_last_name_are_combined(self):
        from newsletter.models import Subscription

        self.run_import("Email Address,First Name,Last Name\na@x.co,Ann,Smith\n")
        self.assertEqual(Subscription.objects.get().name_field, "Ann Smith")

    def test_an_explicit_mapping_overrides_detection(self):
        # Two plausible columns; the caller says which one is the address.
        result = self.run_import(
            "primary,secondary\na@x.co,b@x.co\n", mapping={"email": "secondary"})
        self.assertEqual(result.created, 1)
        self.assertEqual(self.emails(), {"b@x.co"})

    def test_a_dry_run_counts_without_writing(self):
        text = "email,name\na@x.co,Ann\nnope,X\n"
        preview = self.run_import(text, dry_run=True)
        self.assertEqual(self.emails(), set())

        real = self.run_import(text)
        self.assertEqual((preview.created, preview.skipped), (real.created, real.skipped))
        self.assertEqual(self.emails(), {"a@x.co"})

    def test_the_summary_names_every_reason(self):
        result = self.run_import(
            "email,status\na@x.co,subscribed\nb@x.co,unsubscribed\nbad,subscribed\n")
        summary = result.summary()
        self.assertIn("1 new", summary)
        self.assertIn("invalid", summary)
        self.assertIn("opted out", summary)

    def test_consent_still_defaults_to_pending(self):
        from newsletter.models import Subscription

        self.run_import("email\na@x.co\n")
        self.assertFalse(Subscription.objects.get().subscribed)
        self.run_import("email\nb@x.co\n", confirmed=True)
        self.assertTrue(Subscription.objects.get(email_field="b@x.co").subscribed)

    def test_groups_still_apply(self):
        from newsletter.models import Subscription

        self.run_import('email,groups\na@x.co,"Instrument: Guitar; City: Leeds"\n')
        tags = Subscription.objects.get().tags.all()
        self.assertEqual({t.value_label for t in tags}, {"Guitar", "Leeds"})


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class ImportCommandTests(TestCase):
    """`manage.py import_subscribers` — parity with the admin's two-step flow."""

    def setUp(self):
        Newsletter.objects.create(slug="main", title="L", email="h@x.co", sender="X")

    def run_command(self, body, *args):
        path = os.path.join(tempfile.mkdtemp(), "list.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        out, err = StringIO(), StringIO()
        call_command("import_subscribers", path, *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_it_detects_an_unrecognised_header(self):
        output = self.run_command("Subscriber,Sent\na@x.co,0\n")
        self.assertIn("'Subscriber'", output)
        self.assertTrue(Subscription.objects.filter(email_field="a@x.co").exists())

    def test_map_overrides_detection(self):
        self.run_command("primary,secondary\na@x.co,b@x.co\n", "--map", "email=secondary")
        self.assertEqual(
            set(Subscription.objects.values_list("email_field", flat=True)), {"b@x.co"})

    def test_a_bad_map_argument_is_refused(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command("email\na@x.co\n", "--map", "nonsense=Column")

    def test_dry_run_writes_nothing(self):
        output = self.run_command("email\na@x.co\n", "--dry-run")
        self.assertIn("Would import", output)
        self.assertFalse(Subscription.objects.exists())

    def test_no_email_column_fails_loudly(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command("Sent,Opens\n0,0\n1,2\n")


class DateParsingTests(SimpleTestCase):
    """Reading whatever date format the export happened to write."""

    def parse(self, raw, day_first=True):
        from prblm_mailer.csv_io import parse_date_value

        return parse_date_value(raw, day_first)

    def test_the_formats_exports_actually_use(self):
        cases = {
            "2025-09-17 07:16:57": (2025, 9, 17),      # the real file
            "2025-09-17": (2025, 9, 17),
            "2025-09-17T07:16:57Z": (2025, 9, 17),
            "17/09/2025": (2025, 9, 17),
            "17-09-2025": (2025, 9, 17),
            "2025/09/17": (2025, 9, 17),
            "17 Sep 2025": (2025, 9, 17),
            "Sep 17, 2025": (2025, 9, 17),
        }
        for raw, (year, month, day) in cases.items():
            with self.subTest(raw=raw):
                parsed = self.parse(raw)
                self.assertEqual((parsed.year, parsed.month, parsed.day), (year, month, day))

    def test_parsed_dates_are_timezone_aware(self):
        from django.utils import timezone

        self.assertFalse(timezone.is_naive(self.parse("2025-09-17 07:16:57")))

    def test_nonsense_is_rejected_rather_than_guessed(self):
        for raw in ("", "   ", "not a date", "0", "n/a"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.parse(raw))

    def test_day_first_and_month_first_both_work(self):
        self.assertEqual(self.parse("03/04/2025", day_first=True).month, 4)
        self.assertEqual(self.parse("03/04/2025", day_first=False).month, 3)

    def test_the_order_is_decided_from_the_file(self):
        from prblm_mailer.csv_io import detect_date_order

        # 17 can only be a day; 13 can only be a month in a month-first file.
        self.assertTrue(detect_date_order(["17/09/2025", "03/04/2025"]))
        self.assertFalse(detect_date_order(["09/17/2025", "04/03/2025"]))
        self.assertTrue(detect_date_order(["03/04/2025"]))        # no evidence -> day first


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class SubscribeDateImportTests(TestCase):
    """The subscribe date a row ends up with."""

    def setUp(self):
        self.newsletter = Newsletter.objects.create(
            slug="main", title="L", email="h@x.co", sender="X")

    def run_import(self, text, **kw):
        from prblm_mailer.csv_io import import_rows

        return import_rows(text, self.newsletter, **kw)

    def test_a_mapped_date_column_is_detected_and_kept(self):
        # The real file's shape: the date lives under "Subscribed".
        result = self.run_import(
            "Subscriber,Sent,Subscribed\n"
            'a@x.co,0,"2025-09-17 07:16:57"\n')
        self.assertEqual(result.mapping["subscribe_date"], "Subscribed")
        sub = Subscription.objects.get()
        self.assertEqual((sub.subscribe_date.year, sub.subscribe_date.month), (2025, 9))

    def test_a_status_word_column_is_not_read_as_a_date(self):
        result = self.run_import("email,status\na@x.co,subscribed\n")
        self.assertIsNone(result.mapping["subscribe_date"])
        self.assertEqual(result.mapping["status"], "status")

    def test_a_confirmed_row_without_a_date_gets_today(self):
        self.run_import("email\na@x.co\n", confirmed=True)
        self.assertIsNotNone(Subscription.objects.get().subscribe_date)

    def test_a_pending_row_without_a_date_gets_none(self):
        # They haven't subscribed yet; the date fills in when they confirm.
        self.run_import("email\na@x.co\n")
        self.assertIsNone(Subscription.objects.get().subscribe_date)

    def test_an_unreadable_date_is_reported_not_fatal(self):
        # One bad cell among good ones: the column is still a date column, and the
        # row still imports — it just arrives without a date.
        result = self.run_import(
            "email,subscribe date\n"
            "a@x.co,wibble\n"
            "b@x.co,2025-09-17\nc@x.co,2025-09-18\n"
            "d@x.co,2025-09-19\ne@x.co,2025-09-20\n")
        self.assertEqual(result.created, 5)            # nobody lost over a bad date
        self.assertEqual(result.unreadable_dates, 1)
        self.assertIsNone(Subscription.objects.get(email_field="a@x.co").subscribe_date)
        self.assertIsNotNone(Subscription.objects.get(email_field="b@x.co").subscribe_date)

    def test_a_column_of_mostly_rubbish_is_not_treated_as_dates(self):
        result = self.run_import(
            "email,notes\na@x.co,hello\nb@x.co,2025-09-17\nc@x.co,goodbye\n")
        self.assertIsNone(result.mapping["subscribe_date"])

    def test_an_existing_date_is_never_overwritten(self):
        from django.utils import timezone

        original = timezone.now() - datetime.timedelta(days=365)
        sub = Subscription.objects.create(
            newsletter=self.newsletter, email_field="a@x.co")
        Subscription.objects.filter(pk=sub.pk).update(subscribe_date=original)

        self.run_import("email,subscribe date\na@x.co,2025-09-17\n")
        sub.refresh_from_db()
        self.assertEqual(sub.subscribe_date, original)

    def test_an_explicit_mapping_picks_the_date_column(self):
        self.run_import("email,joined on\na@x.co,2024-03-01\n",
                        mapping={"email": "email", "subscribe_date": "joined on"})
        self.assertEqual(Subscription.objects.get().subscribe_date.year, 2024)

    def test_a_dry_run_still_writes_no_dates(self):
        self.run_import("email,subscribe date\na@x.co,2025-09-17\n",
                        confirmed=True, dry_run=True)
        self.assertFalse(Subscription.objects.exists())


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class SubscribeDateAdminTests(TestCase):
    """The Subscribe date dropdown on the mapping screen."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        Newsletter.objects.create(slug="main", title="L", email="h@x.co", sender="X")
        user = get_user_model().objects.create_superuser("admin3", "a3@b.co", "pw")
        self.client.force_login(user)

    def upload(self, body):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post("/admin/subscribers/import/", {
            "csv_file": SimpleUploadedFile("list.csv", body, content_type="text/csv")})

    def test_the_date_column_is_offered_and_pre_selected(self):
        page = self.upload(
            b"Subscriber,Sent,Subscribed\n"
            b'a@x.co,0,"2025-09-17 07:16:57"\n'
            b'b@x.co,0,"2025-09-18 07:16:57"\n')
        self.assertEqual(page.context["mapping"]["subscribe_date"], "Subscribed")
        self.assertContains(page, "Subscribe date")
        self.assertContains(page, "day/month/year")

    def test_the_date_survives_the_import(self):
        page = self.upload(b"email,joined\na@x.co,2024-03-01\nb@x.co,2024-03-02\n")
        data = {"token": page.context["token"], "action": "import"}
        data.update({f"map_{k}": v for k, v in page.context["mapping"].items() if v})
        self.client.post("/admin/subscribers/import/", data)

        self.assertEqual(
            Subscription.objects.get(email_field="a@x.co").subscribe_date.year, 2024)


@override_settings(PRBLM_MAILER={"NEWSLETTER_SLUG": "main"})
class GroupColumnTests(TestCase):
    """A groups column from anywhere, not just this plugin's own export format."""

    def setUp(self):
        self.newsletter = Newsletter.objects.create(
            slug="main", title="L", email="h@x.co", sender="X")

    def run_import(self, text, **kw):
        from prblm_mailer.csv_io import import_rows

        return import_rows(text, self.newsletter, **kw)

    def tags(self, email="a@x.co"):
        sub = Subscription.objects.get(email_field=email)
        return {(t.group_name, t.value_label) for t in sub.tags.all()}

    def test_a_plain_column_is_filed_under_its_own_name(self):
        # The real case: a "Location" column holding "Essex", not "Location: Essex".
        result = self.run_import(
            "email,Location\na@x.co,Essex\n", mapping={"email": "email", "groups": "Location"})
        self.assertEqual(self.tags(), {("Location", "Essex")})
        self.assertEqual(result.grouped, 1)

    def test_the_export_format_still_round_trips(self):
        self.run_import('email,groups\na@x.co,"Instrument: Guitar; City: Leeds"\n')
        self.assertEqual(self.tags(), {("Instrument", "Guitar"), ("City", "Leeds")})

    def test_plain_and_prefixed_values_can_be_mixed(self):
        self.run_import(
            'email,Location\na@x.co,"Essex; City: Leeds"\n',
            mapping={"email": "email", "groups": "Location"})
        self.assertEqual(self.tags(), {("Location", "Essex"), ("City", "Leeds")})

    def test_a_comma_inside_a_value_is_not_a_separator(self):
        self.run_import(
            'email,Location\na@x.co,"Leeds, West Yorkshire"\n',
            mapping={"email": "email", "groups": "Location"})
        self.assertEqual(self.tags(), {("Location", "Leeds, West Yorkshire")})

    def test_blank_cells_contribute_nothing(self):
        result = self.run_import(
            "email,Location\na@x.co,\nb@x.co,Essex\n",
            mapping={"email": "email", "groups": "Location"})
        self.assertEqual(self.tags(), set())
        self.assertEqual(result.grouped, 1)        # only the row that had a value

    def test_an_empty_column_is_reported_as_nothing_grouped(self):
        # The symptom that started this: mapping a column and seeing no effect.
        result = self.run_import(
            "email,Location\na@x.co,\nb@x.co,\n",
            mapping={"email": "email", "groups": "Location"})
        self.assertEqual(result.grouped, 0)

    def test_an_existing_group_answer_is_replaced_not_duplicated(self):
        for value in ("Essex", "Suffolk"):
            self.run_import(f"email,Location\na@x.co,{value}\n",
                            mapping={"email": "email", "groups": "Location"})
        self.assertEqual(self.tags(), {("Location", "Suffolk")})
