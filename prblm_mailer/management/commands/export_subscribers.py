"""Export the newsletter's subscribers to CSV.

    python manage.py export_subscribers                 # to stdout
    python manage.py export_subscribers --output list.csv
    python manage.py export_subscribers --newsletter other-list

Columns: email, name, status, groups, subscribe_date, create_date. The `groups`
column round-trips with import_subscribers ("Group: Value; Group2: Value2").
The same rows back the Subscribers listing's Export button — see `csv_io`.
"""
import csv
import sys

from django.core.management.base import BaseCommand, CommandError

from prblm_mailer.csv_io import export_rows, groups_string, resolve_newsletter  # noqa: F401


class Command(BaseCommand):
    help = "Export newsletter subscribers to CSV."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="File to write (default: stdout).")
        parser.add_argument("--newsletter", help="List slug (default: the configured one).")

    def handle(self, *args, **options):
        newsletter = resolve_newsletter(options["newsletter"])
        if newsletter is None:
            raise CommandError(f"No newsletter list with slug {options['newsletter']!r}.")

        stream = open(options["output"], "w", newline="") if options["output"] else sys.stdout
        try:
            writer = csv.writer(stream)
            count = -1                      # the header row isn't a subscriber
            for row in export_rows(newsletter):
                writer.writerow(row)
                count += 1
        finally:
            if options["output"]:
                stream.close()

        where = options["output"] or "stdout"
        self.stderr.write(self.style.SUCCESS(f"Exported {count} subscriber(s) to {where}."))
