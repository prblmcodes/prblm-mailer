"""Import subscribers into the newsletter list from a CSV.

    python manage.py import_subscribers list.csv                 # as PENDING (default)
    python manage.py import_subscribers list.csv --confirmed     # you already have consent
    python manage.py import_subscribers list.csv --dry-run       # count, write nothing
    python manage.py import_subscribers list.csv --newsletter other-list
    python manage.py import_subscribers list.csv --map email=Subscriber --map name="Full Name"

The columns are found for you: by header name first (email, e-mail, Email Address,
Subscriber…), and failing that by looking at which column actually holds addresses.
`--map` overrides that when a file needs telling. Only the email, name, groups and
status columns are read; dates and engagement columns are ignored.

Consent: rows import as PENDING unless --confirmed. Pending rows never receive a
newsletter until they confirm. Import does NOT send opt-in emails (bulk-mailing a
whole imported list would wreck deliverability) — use --confirmed only for a list
whose consent you already hold. An existing confirmed subscriber is never downgraded
to pending by a plain import, and a row whose status says they unsubscribed
elsewhere is skipped rather than quietly re-added.
"""
from django.core.management.base import BaseCommand, CommandError

from prblm_mailer.csv_io import (MAPPING_KEYS, NoEmailColumn, import_rows,  # noqa: F401
                                 parse_groups, resolve_newsletter)


class Command(BaseCommand):
    help = "Import newsletter subscribers from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file.")
        parser.add_argument("--confirmed", action="store_true",
                            help="Import as confirmed (you already hold consent). Default: pending.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would happen and write nothing.")
        parser.add_argument("--newsletter", help="List slug (default: the configured one).")
        parser.add_argument(
            "--map", action="append", default=[], metavar="FIELD=COLUMN", dest="mapping",
            help="Name a column explicitly, e.g. --map email=Subscriber. Repeatable. "
                 f"Fields: {', '.join(MAPPING_KEYS)}.")

    def handle(self, *args, **options):
        newsletter = resolve_newsletter(options["newsletter"])
        if newsletter is None:
            raise CommandError(f"No newsletter list with slug {options['newsletter']!r}.")

        mapping = {}
        for pair in options["mapping"]:
            field, _, column = pair.partition("=")
            field = field.strip()
            if field not in MAPPING_KEYS or not column.strip():
                raise CommandError(
                    f"--map wants FIELD=COLUMN with FIELD one of {', '.join(MAPPING_KEYS)}; "
                    f"got {pair!r}.")
            mapping[field] = column.strip()

        try:
            handle = open(options["csv_path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Cannot open {options['csv_path']}: {exc}") from exc

        with handle:
            try:
                result = import_rows(handle, newsletter, confirmed=options["confirmed"],
                                     mapping=mapping or None, dry_run=options["dry_run"])
            except NoEmailColumn as exc:
                raise CommandError(str(exc)) from exc

        for email in result.bad_emails:
            self.stderr.write(f"  skipped invalid email: {email!r}")
        self.stdout.write(f"Email column: {result.mapping.get('email')!r}")
        state = "confirmed" if options["confirmed"] else "pending"
        prefix = "Would import" if options["dry_run"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{prefix} as {state}: {result.summary()}."))
