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
import csv
import re

from django.core.management.base import BaseCommand, CommandError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_groups(raw):
    """"Group: Value; Group2: Value2" -> [("Group","Value"), ("Group2","Value2")]."""
    pairs = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if ":" in chunk:
            group, value = chunk.split(":", 1)
            group, value = group.strip(), value.strip()
            if group and value:
                pairs.append((group, value))
    return pairs


class Command(BaseCommand):
    help = "Import newsletter subscribers from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file.")
        parser.add_argument("--confirmed", action="store_true",
                            help="Import as confirmed (you already hold consent). Default: pending.")
        parser.add_argument("--newsletter", help="List slug (default: the configured one).")

    def handle(self, *args, **options):
        from newsletter.models import Newsletter, Subscription
        from prblm_mailer.conf import get_setting
        from prblm_mailer.segments import apply_tags

        slug = options["newsletter"] or get_setting("NEWSLETTER_SLUG")
        newsletter = Newsletter.objects.filter(slug=slug).first()
        if newsletter is None:
            raise CommandError(f"No newsletter list with slug {slug!r}.")

        confirmed = options["confirmed"]
        created = updated = skipped = 0

        try:
            handle = open(options["csv_path"], newline="")
        except OSError as exc:
            raise CommandError(f"Cannot open {options['csv_path']}: {exc}") from exc

        with handle:
            reader = csv.DictReader(handle)
            # Case-insensitive header lookup.
            for raw_row in reader:
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
                email = row.get("email", "")
                if not _EMAIL_RE.match(email):
                    skipped += 1
                    if email:
                        self.stderr.write(f"  skipped invalid email: {email!r}")
                    continue

                name = row.get("name", "")
                groups = parse_groups(row.get("groups", ""))

                sub, was_created = Subscription.objects.get_or_create(
                    newsletter=newsletter, email_field=email,
                    defaults={"name_field": name},
                )

                # Set subscription state with .update(), bypassing django-newsletter's
                # save() (which treats unsubscribed True->False as instant consent).
                # Never downgrade an existing confirmed subscriber on a plain import.
                if was_created:
                    Subscription.objects.filter(pk=sub.pk).update(
                        subscribed=confirmed, unsubscribed=False)
                    created += 1
                else:
                    if confirmed:
                        Subscription.objects.filter(pk=sub.pk).update(
                            subscribed=True, unsubscribed=False)
                    updated += 1

                if name and not sub.name_field:
                    Subscription.objects.filter(pk=sub.pk).update(name_field=name)

                sub.refresh_from_db()
                apply_tags(sub, groups)

        state = "confirmed" if confirmed else "pending"
        self.stdout.write(self.style.SUCCESS(
            f"Imported as {state}: {created} new, {updated} existing, {skipped} skipped."))
