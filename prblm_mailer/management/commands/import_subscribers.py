"""Import subscribers into the newsletter list from a CSV.

    python manage.py import_subscribers list.csv                 # as PENDING (default)
    python manage.py import_subscribers list.csv --confirmed     # you already have consent
    python manage.py import_subscribers list.csv --newsletter other-list

The CSV needs an `email` column; `name` and `groups` are optional. `groups` is
"Group: Value; Group2: Value2" (what export_subscribers writes). Other columns are
ignored. Rows with a missing or invalid email are skipped and counted.

Consent: rows import as PENDING unless --confirmed. Pending rows never receive a
newsletter until they confirm. Import does NOT send opt-in emails (bulk-mailing a
whole imported list would wreck deliverability) — use --confirmed only for a list
whose consent you already hold. An existing confirmed subscriber is never downgraded
to pending by a plain import.
"""
from django.core.management.base import BaseCommand, CommandError

from prblm_mailer.csv_io import import_rows, parse_groups, resolve_newsletter  # noqa: F401


class Command(BaseCommand):
    help = "Import newsletter subscribers from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file.")
        parser.add_argument("--confirmed", action="store_true",
                            help="Import as confirmed (you already hold consent). Default: pending.")
        parser.add_argument("--newsletter", help="List slug (default: the configured one).")

    def handle(self, *args, **options):
        newsletter = resolve_newsletter(options["newsletter"])
        if newsletter is None:
            raise CommandError(f"No newsletter list with slug {options['newsletter']!r}.")

        try:
            handle = open(options["csv_path"], newline="")
        except OSError as exc:
            raise CommandError(f"Cannot open {options['csv_path']}: {exc}") from exc

        with handle:
            created, updated, skipped, bad = import_rows(
                handle, newsletter, confirmed=options["confirmed"])

        for email in bad:
            self.stderr.write(f"  skipped invalid email: {email!r}")
        state = "confirmed" if options["confirmed"] else "pending"
        self.stdout.write(self.style.SUCCESS(
            f"Imported as {state}: {created} new, {updated} existing, {skipped} skipped."))
