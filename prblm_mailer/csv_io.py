"""CSV import/export of subscribers, shared by the management commands and the admin.

The two entry points (`manage.py import_subscribers` and the Subscribers listing's
Import button) must agree on what a CSV means — consent semantics above all — so the
rules live here once rather than in each caller.

Columns: email, name, status, groups, subscribe_date, create_date. `groups` is
"Group: Value; Group2: Value2", which round-trips through both directions.
"""
import csv
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EXPORT_HEADER = ["email", "name", "status", "groups", "subscribe_date", "create_date"]


def groups_string(subscription):
    return "; ".join(
        f"{tag.group_name}: {tag.value_label}" for tag in subscription.tags.all()
    )


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


def subscriptions_for(newsletter):
    from newsletter.models import Subscription

    return (
        Subscription.objects.filter(newsletter=newsletter)
        .prefetch_related("tags").order_by("email_field")
    )


def export_rows(newsletter):
    """Yield the header, then one row per subscriber — a generator, so the admin can
    stream a large list without building the whole file in memory."""
    yield EXPORT_HEADER
    for sub in subscriptions_for(newsletter):
        status = ("unsubscribed" if sub.unsubscribed
                  else "confirmed" if sub.subscribed else "pending")
        yield [
            sub.email_field, sub.name_field or "", status, groups_string(sub),
            sub.subscribe_date.isoformat() if sub.subscribe_date else "",
            sub.create_date.isoformat() if sub.create_date else "",
        ]


def import_rows(lines, newsletter, confirmed=False):
    """Import an iterable of CSV lines. Returns (created, updated, skipped, bad_emails).

    Consent: rows land as **pending** unless `confirmed`, and no opt-in emails are
    sent — bulk-mailing an imported list is how a sending domain gets burned. An
    already-confirmed subscriber is never downgraded by a plain import.
    """
    from newsletter.models import Subscription

    from .segments import apply_tags

    created = updated = skipped = 0
    bad_emails = []

    for raw_row in csv.DictReader(lines):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        email = row.get("email", "")
        if not _EMAIL_RE.match(email):
            skipped += 1
            if email:
                bad_emails.append(email)
            continue

        name = row.get("name", "")
        groups = parse_groups(row.get("groups", ""))

        sub, was_created = Subscription.objects.get_or_create(
            newsletter=newsletter, email_field=email, defaults={"name_field": name},
        )

        # Set state with .update(), bypassing django-newsletter's save() (which reads
        # unsubscribed True->False as instant consent).
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

    return created, updated, skipped, bad_emails


def resolve_newsletter(slug=None):
    """The list to import into / export from, or None."""
    from newsletter.models import Newsletter

    from .conf import get_setting

    return Newsletter.objects.filter(slug=slug or get_setting("NEWSLETTER_SLUG")).first()
