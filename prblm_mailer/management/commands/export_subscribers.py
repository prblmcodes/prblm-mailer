"""Export the newsletter's subscribers to CSV.

    python manage.py export_subscribers                 # to stdout
    python manage.py export_subscribers --output list.csv
    python manage.py export_subscribers --newsletter other-list

Columns: email, name, status, groups, subscribe_date, create_date. The `groups`
column round-trips with import_subscribers ("Group: Value; Group2: Value2").
"""
import csv
import sys

from django.core.management.base import BaseCommand, CommandError


def groups_string(subscription):
    return "; ".join(
        f"{tag.group_name}: {tag.value_label}" for tag in subscription.tags.all()
    )


class Command(BaseCommand):
    help = "Export newsletter subscribers to CSV."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="File to write (default: stdout).")
        parser.add_argument("--newsletter", help="List slug (default: the configured one).")

    def handle(self, *args, **options):
        from newsletter.models import Newsletter, Subscription
        from prblm_mailer.conf import get_setting

        slug = options["newsletter"] or get_setting("NEWSLETTER_SLUG")
        newsletter = Newsletter.objects.filter(slug=slug).first()
        if newsletter is None:
            raise CommandError(f"No newsletter list with slug {slug!r}.")

        subscriptions = (
            Subscription.objects.filter(newsletter=newsletter)
            .prefetch_related("tags").order_by("email_field")
        )

        stream = open(options["output"], "w", newline="") if options["output"] else sys.stdout
        try:
            writer = csv.writer(stream)
            writer.writerow(["email", "name", "status", "groups", "subscribe_date", "create_date"])
            count = 0
            for sub in subscriptions:
                status = ("unsubscribed" if sub.unsubscribed
                          else "confirmed" if sub.subscribed else "pending")
                writer.writerow([
                    sub.email_field, sub.name_field or "", status, groups_string(sub),
                    sub.subscribe_date.isoformat() if sub.subscribe_date else "",
                    sub.create_date.isoformat() if sub.create_date else "",
                ])
                count += 1
        finally:
            if options["output"]:
                stream.close()

        where = options["output"] or "stdout"
        self.stderr.write(self.style.SUCCESS(f"Exported {count} subscriber(s) to {where}."))
