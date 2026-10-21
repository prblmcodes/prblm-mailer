"""CSV import/export of subscribers, shared by the management commands and the admin.

The two entry points (`manage.py import_subscribers` and the Subscribers listing's
Import button) must agree on what a CSV means — consent semantics above all — so the
rules live here once rather than in each caller. The admin's preview is the same code
path with `dry_run=True`, so what it promises is what the import does.

Export columns: email, name, status, groups, subscribe_date, create_date. `groups` is
"Group: Value; Group2: Value2", which round-trips through both directions.

Import accepts a CSV from anywhere: the columns are found by header alias, then by
looking at the values, and the caller can override the result with an explicit
`mapping`. Dates and engagement columns are read by nobody — only email, name,
groups and status mean anything on the way in.
"""
import csv
import datetime
import io
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EXPORT_HEADER = ["email", "name", "status", "groups", "subscribe_date", "create_date"]

# Header names seen in the wild, in priority order within each group. Compared
# lower-cased with punctuation stripped, so "E-Mail Address" matches "email address".
EMAIL_ALIASES = (
    "email", "email address", "e mail", "e mail address", "emailaddress",
    "subscriber email", "subscriber", "contact email", "mail", "address",
)
NAME_ALIASES = ("name", "full name", "display name", "contact name", "subscriber name")
FIRST_NAME_ALIASES = ("first name", "firstname", "given name", "forename")
LAST_NAME_ALIASES = ("last name", "lastname", "surname", "family name")
GROUP_ALIASES = ("groups", "group", "tags", "tag", "interests", "segments")
STATUS_ALIASES = ("status", "subscription status", "member status", "state", "subscribed")
# "subscribed" sits in both lists on purpose: an export uses it for a status word or
# for a date, and only the values can say which. `detect_columns` decides by content.
DATE_ALIASES = (
    "subscribe date", "subscribed", "subscription date", "date subscribed",
    "signup date", "sign up date", "opt in date", "date added", "joined",
    "confirmed at", "created", "created at", "date",
)

# Status values that mean "this person has already left, or can't be reached".
# Importing them would quietly undo an unsubscribe someone made elsewhere, which is
# the one mistake in this module that costs real money (a complaint, not a bad row).
OPTED_OUT_STATUSES = {
    "unsubscribed", "unsub", "opted out", "opt out", "optout", "cleaned", "bounced",
    "hard bounced", "complained", "spam", "abuse", "archived", "inactive", "removed",
}

# How many rows to read before deciding which column holds the email, and how
# strongly they must agree. 70% leaves room for the odd blank or malformed cell
# while still refusing a column that merely contains an address here and there.
SNIFF_ROWS = 20
SNIFF_THRESHOLD = 0.7

MAPPING_KEYS = ("email", "name", "first_name", "last_name", "groups", "status",
                "subscribe_date")


class NoEmailColumn(ValueError):
    """Raised when no column can be read as an email address.

    A dedicated exception because the alternative — the behaviour this module used
    to have — is skipping every row and reporting a cheerful "0 imported".
    """


class ImportResult(tuple):
    """`(created, updated, skipped, bad_emails)`, plus the detail behind `skipped`.

    A 4-tuple subclass rather than a NamedTuple so that
    `created, updated, skipped, bad = import_rows(...)` keeps working for anyone
    already calling this; the breakdown and the mapping ride along as attributes.
    """

    def __new__(cls, created, updated, skipped, bad_emails,
                invalid=0, duplicates=0, opted_out=0, mapping=None, total=0,
                unreadable_dates=0, day_first=True):
        self = super().__new__(cls, (created, updated, skipped, bad_emails))
        self.created, self.updated, self.skipped = created, updated, skipped
        self.bad_emails = bad_emails
        self.invalid, self.duplicates, self.opted_out = invalid, duplicates, opted_out
        self.mapping = mapping or {}
        self.total = total
        # A date nobody can read never costs a subscriber — it is reported instead.
        self.unreadable_dates = unreadable_dates
        self.day_first = day_first
        return self

    def summary(self):
        """One line for a success message, naming every reason a row was dropped."""
        parts = [f"{self.created} new", f"{self.updated} already on the list",
                 f"{self.skipped} skipped"]
        reasons = []
        if self.invalid:
            reasons.append(f"{self.invalid} invalid")
        if self.duplicates:
            reasons.append(f"{self.duplicates} repeated in the file")
        if self.opted_out:
            reasons.append(f"{self.opted_out} opted out elsewhere")
        return ", ".join(parts) + (f" ({'; '.join(reasons)})" if reasons else "")


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


# --------------------------------------------------------------------- reading


def _normalise_header(name):
    """"E-Mail_Address " -> "e mail address", so one alias covers many spellings."""
    return re.sub(r"[\s_\-./]+", " ", (name or "").strip().lower()).strip()


def read_table(lines):
    """`(headers, rows)` from CSV text, as forgiving as it can be about the shape.

    Sniffs the delimiter (comma, semicolon, tab or pipe — a European export is
    routinely semicolon-separated) and whether there is a header row at all. A
    headerless file gets synthetic "Column 1..N" headers so the mapping UI has
    something to put in its dropdowns.
    """
    text = lines if isinstance(lines, str) else "".join(lines)
    text = text.lstrip("﻿")                      # a BOM survives some exports
    if not text.strip():
        return [], []

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.get_dialect("excel")            # a single column has no delimiter
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return [], []

    if _is_header_row(rows[0]):
        headers, data = [h.strip() for h in rows[0]], rows[1:]
    else:
        headers, data = [f"Column {i + 1}" for i in range(len(rows[0]))], rows

    # Pad short rows and ignore trailing extras, so one ragged line can't shift
    # every value after it into the wrong column.
    table = [
        {headers[i]: (row[i].strip() if i < len(row) else "") for i in range(len(headers))}
        for row in data
    ]
    return headers, table


def _is_header_row(cells):
    """Whether the first row names the columns rather than being one of them.

    `csv.Sniffer().has_header()` guesses from column types and gets a short,
    all-text file wrong often enough to lose somebody's first subscriber — it read
    `email,status` as data. Asking "does this row look like data?" is both narrower
    and far more reliable: real data here carries an address, or is numeric.
    """
    values = [c.strip() for c in cells if c.strip()]
    if not values:
        return True
    if any(_EMAIL_RE.match(v) for v in values):
        return False
    return not all(re.match(r"^[\d\s./:+-]+$", v) for v in values)


def detect_columns(headers, rows=()):
    """Guess which header is which. Returns a mapping with `MAPPING_KEYS`.

    Header aliases first, because a name is a stated intention. Only when nothing
    matches does it fall back to reading the values — and then it wants most of the
    sample to look like email addresses, so a "notes" column holding the odd address
    can't win.
    """
    by_normal = {}
    for header in headers:
        by_normal.setdefault(_normalise_header(header), header)

    def first_alias(aliases):
        for alias in aliases:
            if alias in by_normal:
                return by_normal[alias]
        return None

    mapping = {
        "email": first_alias(EMAIL_ALIASES),
        "name": first_alias(NAME_ALIASES),
        "first_name": first_alias(FIRST_NAME_ALIASES),
        "last_name": first_alias(LAST_NAME_ALIASES),
        "groups": first_alias(GROUP_ALIASES),
        "status": first_alias(STATUS_ALIASES),
    }

    # "Subscribed" is both a status alias and, in some exports, a date column. If it
    # holds no status-ish word, leave it alone rather than skip rows over a date.
    if mapping["status"] and not _looks_like_status(mapping["status"], rows):
        mapping["status"] = None

    # Only believe a date column that holds dates — and never the column already
    # taken as the status, which in a real export is often the same header.
    date_header = first_alias(DATE_ALIASES)
    if date_header and date_header != mapping["status"] and _looks_like_date(date_header, rows):
        mapping["subscribe_date"] = date_header
    else:
        mapping["subscribe_date"] = None

    if not mapping["email"]:
        mapping["email"] = _sniff_email_column(headers, rows)
    return mapping


def _looks_like_status(header, rows):
    """True if the column's values read as words rather than dates or numbers."""
    values = [r.get(header, "") for r in rows[:SNIFF_ROWS] if r.get(header, "").strip()]
    if not values:
        return False
    wordy = sum(1 for v in values if re.search(r"[a-z]", v, re.I) and not re.match(r"^\d", v))
    return wordy / len(values) >= SNIFF_THRESHOLD


def _sniff_email_column(headers, rows):
    """The column whose values actually look like email addresses, or None."""
    best, best_score = None, 0.0
    for header in headers:
        values = [r.get(header, "") for r in rows[:SNIFF_ROWS] if r.get(header, "").strip()]
        if not values:
            continue
        score = sum(1 for v in values if _EMAIL_RE.match(v)) / len(values)
        if score >= SNIFF_THRESHOLD and score > best_score:
            best, best_score = header, score
    return best


# Tried in order after ISO. The slash/dot forms come in both orders, and which one
# a file means is decided per column by `detect_date_order` rather than assumed.
_DATE_FORMATS_DAY_FIRST = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                           "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%d.%m.%Y")
_DATE_FORMATS_MONTH_FIRST = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                             "%m-%d-%Y %H:%M:%S", "%m-%d-%Y", "%m.%d.%Y")
_DATE_FORMATS_UNAMBIGUOUS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
                             "%b %d, %Y", "%B %d, %Y", "%d %b %Y %H:%M:%S")


def detect_date_order(values):
    """True when a column's dates are day-first.

    Decided from the file rather than from a setting: `03/04/2025` is March in a US
    export and April in a British one, and only a value like `17/09/2025` settles
    it. With no evidence either way it stays day-first, and the import reports which
    reading it used so a wrong guess is visible rather than silent.
    """
    day_first_evidence = month_first_evidence = 0
    for value in values:
        parts = re.split(r"[/.\-]", (value or "").strip())[:2]
        if len(parts) < 2 or not all(p.isdigit() for p in parts):
            continue
        first, second = int(parts[0]), int(parts[1])
        if first > 12 and second <= 12:
            day_first_evidence += 1
        elif second > 12 and first <= 12:
            month_first_evidence += 1
    return month_first_evidence <= day_first_evidence


def parse_date_value(raw, day_first=True):
    """A timezone-aware datetime from whatever the export wrote, or None."""
    from django.utils import timezone

    value = (raw or "").strip()
    if not value:
        return None

    parsed = None
    if value.isdigit() and len(value) in (10, 13):         # a unix timestamp
        try:
            seconds = int(value) / (1000 if len(value) == 13 else 1)
            parsed = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
        except (ValueError, OSError, OverflowError):
            parsed = None
    if parsed is None:
        iso = value.replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(iso)
        except ValueError:
            parsed = None
    if parsed is None:
        ordered = _DATE_FORMATS_DAY_FIRST if day_first else _DATE_FORMATS_MONTH_FIRST
        for fmt in ordered + _DATE_FORMATS_UNAMBIGUOUS:
            try:
                parsed = datetime.datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None

    if timezone.is_naive(parsed):
        # USE_TZ is on in any modern Django; a naive value here would warn and be
        # read as UTC anyway, so say explicitly that it is local time.
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _looks_like_date(header, rows):
    """True if most of a column's values parse as a date."""
    values = [r.get(header, "") for r in rows[:SNIFF_ROWS] if r.get(header, "").strip()]
    if not values:
        return False
    day_first = detect_date_order(values)
    readable = sum(1 for v in values if parse_date_value(v, day_first))
    return readable / len(values) >= SNIFF_THRESHOLD


def sample_rows(rows, limit=5):
    """The first few rows, for the mapping screen's preview."""
    return rows[:limit]


# --------------------------------------------------------------------- importing


def _row_name(row, mapping):
    """The subscriber's name: a single name column, else first + last combined."""
    if mapping.get("name"):
        name = (row.get(mapping["name"]) or "").strip()
        if name:
            return name
    parts = [(row.get(mapping.get(key)) or "").strip() for key in ("first_name", "last_name")]
    return " ".join(p for p in parts if p)


def _resolve_subscribe_date(when, confirmed):
    """The date a row should carry: the file's, else today for a confirmed import.

    A pending row deliberately gets nothing — they haven't subscribed yet, and the
    date fills itself in when they click the confirmation link.
    """
    from django.utils import timezone

    if when:
        return when
    return timezone.now() if confirmed else None


def import_rows(lines, newsletter, confirmed=False, mapping=None, dry_run=False):
    """Import CSV text. Returns an `ImportResult`.

    `mapping` overrides the detected columns; omit it and the columns are found by
    `detect_columns`. `dry_run` counts everything and writes nothing, which is what
    the admin's preview uses — so the numbers it shows are the numbers it will do.

    Consent: rows land as **pending** unless `confirmed`, and no opt-in emails are
    sent — bulk-mailing an imported list is how a sending domain gets burned. An
    already-confirmed subscriber is never downgraded by a plain import, and a row
    whose status says they unsubscribed elsewhere is skipped outright.
    """
    from newsletter.models import Subscription

    from .segments import apply_tags

    headers, rows = read_table(lines)
    mapping = {key: (mapping or {}).get(key) for key in MAPPING_KEYS} if mapping \
        else detect_columns(headers, rows)
    if not mapping.get("email"):
        raise NoEmailColumn(
            "Couldn't find an email column. The headers were: "
            + (", ".join(headers) if headers else "(the file is empty)")
        )

    created = updated = invalid = duplicates = opted_out = unreadable_dates = 0
    bad_emails = []
    seen = set()

    date_header = mapping.get("subscribe_date")
    day_first = detect_date_order(
        [r.get(date_header, "") for r in rows[:SNIFF_ROWS]]) if date_header else True

    for row in rows:
        email = (row.get(mapping["email"]) or "").strip().lower()
        if not _EMAIL_RE.match(email):
            invalid += 1
            if email:
                bad_emails.append(email)
            continue
        if email in seen:
            duplicates += 1
            continue
        seen.add(email)

        if mapping.get("status"):
            status = (row.get(mapping["status"]) or "").strip().lower()
            if status in OPTED_OUT_STATUSES:
                opted_out += 1
                continue

        name = _row_name(row, mapping)
        groups = parse_groups(row.get(mapping.get("groups")) or "")

        raw_date = (row.get(date_header) or "").strip() if date_header else ""
        when = parse_date_value(raw_date, day_first) if raw_date else None
        if raw_date and when is None:
            # Never skip a subscriber over a date nobody can read: fall back to the
            # same rule as a row with no date at all, and report the count.
            unreadable_dates += 1
        subscribe_date = _resolve_subscribe_date(when, confirmed)

        if dry_run:
            # Matched case-insensitively, exactly as the write below does.
            exists = Subscription.objects.filter(
                newsletter=newsletter, email_field__iexact=email).exists()
            updated += 1 if exists else 0
            created += 0 if exists else 1
            continue

        sub = Subscription.objects.filter(
            newsletter=newsletter, email_field__iexact=email).first()
        was_created = sub is None
        if was_created:
            sub = Subscription.objects.create(
                newsletter=newsletter, email_field=email, name_field=name)
            created += 1
        else:
            updated += 1

        # Set state with .update(), bypassing django-newsletter's save() (which reads
        # unsubscribed True->False as instant consent).
        if was_created:
            Subscription.objects.filter(pk=sub.pk).update(
                subscribed=confirmed, unsubscribed=False)
        elif confirmed:
            Subscription.objects.filter(pk=sub.pk).update(
                subscribed=True, unsubscribed=False)

        if name and not sub.name_field:
            Subscription.objects.filter(pk=sub.pk).update(name_field=name)

        sub.refresh_from_db()

        # Fill the date, never overwrite one: a real signup date already on the row
        # is better evidence than anything a later import brings.
        if subscribe_date and not sub.subscribe_date:
            Subscription.objects.filter(pk=sub.pk).update(subscribe_date=subscribe_date)

        apply_tags(sub, groups)

    return ImportResult(
        created, updated, invalid + duplicates + opted_out, bad_emails,
        invalid=invalid, duplicates=duplicates, opted_out=opted_out,
        mapping=mapping, total=len(rows),
        unreadable_dates=unreadable_dates, day_first=day_first,
    )


def resolve_newsletter(slug=None):
    """The list to import into / export from, or None."""
    from newsletter.models import Newsletter

    from .conf import get_setting

    return Newsletter.objects.filter(slug=slug or get_setting("NEWSLETTER_SLUG")).first()
