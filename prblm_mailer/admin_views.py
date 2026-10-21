"""Wagtail-admin views: the dedicated send page, the confirm step, and duplicate.

A separate page from the snippet editor so "write it" and "send it" stay distinct.
Sending is synchronous — one Mailgun batch call covers 1000 recipients.
"""
import pathlib
import re

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from wagtail.admin.auth import require_admin_access

# What each non-live delivery mode actually did, for the admin success message —
# so a dry run doesn't misleadingly say "sent". None ⇒ a real Mailgun send.
_DELIVERY_NOTE = {
    "dry_run": "Dry run — nothing was actually emailed (DELIVERY='dry_run'). "
               "The details are in the server log.",
    "console": "Rendered to the terminal — check your server log. "
               "Nothing was emailed to real recipients (DELIVERY='console').",
    "local": "Delivered to your local inbox (e.g. mailcrab/mailpit). "
             "Nothing went to real recipients (DELIVERY='local').",
}


@require_admin_access
def send_newsletter(request, pk):
    """Preview, send a test, or pick the audience and proceed to confirm."""
    from . import audience, sending
    from .models import Broadcast, SubscriberTag

    broadcast = get_object_or_404(Broadcast, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "proceed":
            if broadcast.is_sent:
                messages.error(request, "This newsletter has already been sent.")
                return redirect(reverse("prblm_mailer_send", args=[pk]))

            chosen = SubscriberTag.objects.filter(pk__in=request.POST.getlist("groups"))
            ungrouped = bool(request.POST.get("include_ungrouped"))
            if not chosen and not ungrouped:
                # Empty selection would fall through to "everyone" — the opposite of
                # what unticking everything looks like it means.
                messages.error(request, "Pick at least one group to send to.")
                return redirect(reverse("prblm_mailer_send", args=[pk]))

            broadcast.send_to_tags.set(chosen)
            broadcast.include_ungrouped = ungrouped
            broadcast.save(update_fields=["include_ungrouped", "updated_at"])
            return redirect(reverse("prblm_mailer_confirm", args=[pk]))

        if action == "test":
            email = (request.POST.get("test_email") or "").strip()
            if not email:
                messages.error(request, "Enter an email address to send the test to.")
            else:
                try:
                    sending.send_test(broadcast, email)
                except Exception as exc:  # noqa: BLE001
                    messages.error(request, f"Test send failed: {exc}")
                else:
                    note = _DELIVERY_NOTE.get(sending.delivery_mode())
                    if note:
                        messages.success(request, f"Test processed for {email}. {note}")
                    else:
                        messages.success(request, f"Test email sent to {email}.")
            return redirect(reverse("prblm_mailer_send", args=[pk]))

    preview_html = ""
    try:
        preview_html = sending.render_email_html(broadcast)
    except Exception as exc:  # noqa: BLE001 — a broken body must not 500 the page
        messages.error(request, f"Could not render a preview: {exc}")

    # Never narrowed → everyone → show every box ticked, not an empty-looking form.
    chosen_ids = set(broadcast.send_to_tags.values_list("pk", flat=True))
    untouched = not chosen_ids and not broadcast.include_ungrouped
    group_choices = [
        {"tag": tag, "checked": untouched or tag.pk in chosen_ids}
        for tag in SubscriberTag.objects.all()
    ]

    return render(request, "prblm_mailer/send_newsletter.html", {
        "broadcast": broadcast,
        "group_choices": group_choices,
        "include_ungrouped": untouched or broadcast.include_ungrouped,
        "preview_html": preview_html,
        "engagement": broadcast.engagement_stats() if broadcast.is_sent else None,
    })


@require_admin_access
def confirm_send(request, pk):
    """Show exactly who this is about to go to, then send it. A page, not a JS confirm."""
    from . import audience, sending
    from .models import Broadcast

    broadcast = get_object_or_404(Broadcast, pk=pk)
    if broadcast.is_sent:
        messages.info(request, "This newsletter has already been sent.")
        return redirect(reverse("prblm_mailer_send", args=[pk]))

    recipient_count = audience.resolve(broadcast).count()

    if request.method == "POST":
        if recipient_count == 0:
            messages.error(request, "Nobody to send to — nothing was sent.")
            return redirect(reverse("prblm_mailer_send", args=[pk]))
        try:
            sending.send_broadcast(broadcast.pk)
            broadcast.refresh_from_db()
            note = _DELIVERY_NOTE.get(sending.delivery_mode())
            if note:
                messages.success(
                    request,
                    f"Processed {broadcast.emails_sent} recipient(s). {note}",
                )
            else:
                messages.success(
                    request,
                    f"Sent to {broadcast.emails_sent} subscriber(s)."
                    + (f" {broadcast.emails_failed} failed." if broadcast.emails_failed else ""),
                )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Send failed: {exc}")
        return redirect(reverse("prblm_mailer_send", args=[pk]))

    return render(request, "prblm_mailer/confirm_send.html", {
        "broadcast": broadcast,
        "recipient_count": recipient_count,
        "audience_label": audience.describe(broadcast),
        "groups": broadcast.send_to_tags.all(),
        "include_ungrouped": broadcast.include_ungrouped,
    })


@require_admin_access
def duplicate_newsletter(request, pk):
    """Copy a sent newsletter into a fresh draft (a sent one is locked). POST-only."""
    from .models import Broadcast

    original = get_object_or_404(Broadcast, pk=pk)
    if request.method != "POST":
        return redirect(reverse("prblm_mailer_send", args=[pk]))

    copy = original.duplicate()
    messages.success(request, f"Duplicated as “{copy.subject}”. Edit and send it below.")
    return redirect(reverse("wagtailsnippets_prblm_mailer_broadcast:edit", args=[copy.pk]))


@require_admin_access
def export_subscribers(request):
    """Stream the subscriber list as a CSV download.

    Streamed rather than built in memory: the same view has to serve a list of
    fifty and a list of fifty thousand.
    """
    import csv

    from django.http import Http404, StreamingHttpResponse
    from django.utils import timezone

    from .csv_io import export_rows, resolve_newsletter

    newsletter = resolve_newsletter()
    if newsletter is None:
        raise Http404("No newsletter list configured.")

    class _Echo:
        """A file-like object that returns what it is handed — csv.writer writes
        into this, and each row goes straight out to the client."""

        def write(self, value):
            return value

    writer = csv.writer(_Echo())
    filename = f"subscribers-{newsletter.slug}-{timezone.now():%Y%m%d}.csv"
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in export_rows(newsletter)),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# Where an upload waits between the two steps of the import. Not the session:
# a subscriber list is far too big for a cookie and has no business in one.
IMPORT_STASH_DIR = "prblm-mailer-imports"
IMPORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
STASH_MAX_AGE = 6 * 60 * 60


def _stash_path(token):
    """The temp file for `token`, or None if the token isn't one we issued.

    The pattern check is what stops a crafted token walking out of the directory.
    """
    import tempfile

    if not IMPORT_TOKEN_RE.match(token or ""):
        return None
    return pathlib.Path(tempfile.gettempdir()) / IMPORT_STASH_DIR / f"{token}.csv"


def _stash_upload(text):
    """Park the uploaded text and return its token, sweeping anything stale first."""
    import secrets
    import tempfile
    import time

    directory = pathlib.Path(tempfile.gettempdir()) / IMPORT_STASH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STASH_MAX_AGE
    for old in directory.glob("*.csv"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:  # another request got there first
            pass

    token = secrets.token_urlsafe(24)
    path = directory / f"{token}.csv"
    path.write_text(text, encoding="utf-8")
    return token


def _decode(upload):
    """The upload as text. Falls back to cp1252, which is what a spreadsheet on
    Windows writes when it doesn't write UTF-8 — and which decodes any byte, so
    this never leaves the admin with 'that file isn't text'."""
    raw = upload.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


@require_admin_access
def import_subscribers(request):
    """Upload a CSV, confirm which column is which, then import. Same rules as the
    management command.

    Two steps because the column names in a real export are anybody's guess: the
    plugin detects them, shows you what it found over a sample of the file and a
    count of what would happen, and lets you correct it before anything is written.

    Consent is unchanged and is the whole story: rows land pending unless the
    uploader states they already hold consent, no opt-in emails are sent either way,
    and a row whose status says they unsubscribed elsewhere is never added
    (see `csv_io.import_rows`).
    """
    from django.http import Http404

    from .csv_io import (MAPPING_KEYS, NoEmailColumn, detect_columns, import_rows,
                         read_table, resolve_newsletter, sample_rows)

    newsletter = resolve_newsletter()
    if newsletter is None:
        raise Http404("No newsletter list configured.")

    if request.method != "POST":
        return render(request, "prblm_mailer/import_subscribers.html",
                      {"newsletter": newsletter})

    token = request.POST.get("token") or ""
    if token:
        path = _stash_path(token)
        if path is None or not path.exists():
            messages.error(request, "That upload has expired — choose the file again.")
            return redirect(reverse("prblm_mailer_import_subscribers"))
        text = path.read_text(encoding="utf-8")
    else:
        upload = request.FILES.get("csv_file")
        if upload is None:
            messages.error(request, "Choose a CSV file to import.")
            return redirect(reverse("prblm_mailer_import_subscribers"))
        text = _decode(upload)
        token = _stash_upload(text)

    headers, rows = read_table(text)
    if not headers:
        messages.error(request, "That file has no readable rows.")
        return redirect(reverse("prblm_mailer_import_subscribers"))

    # The dropdowns on the mapping screen, once chosen, win over detection.
    chosen = {key: request.POST.get(f"map_{key}") or None for key in MAPPING_KEYS}
    mapping = chosen if any(chosen.values()) else detect_columns(headers, rows)
    mapping = {key: (value if value in headers else None) for key, value in mapping.items()}

    confirmed = request.POST.get("confirmed") == "on"
    committing = request.POST.get("action") == "import"

    try:
        result = import_rows(text, newsletter, confirmed=confirmed,
                             mapping=mapping if mapping.get("email") else None,
                             dry_run=not committing)
    except NoEmailColumn:
        result = None
    except Exception as exc:  # noqa: BLE001 — a bad CSV must not 500 the admin
        messages.error(request, f"Import failed: {exc}")
        return redirect(reverse("prblm_mailer_import_subscribers"))

    if committing and result is not None:
        _stash_path(token).unlink(missing_ok=True)
        state = "confirmed" if confirmed else "pending (they must still confirm)"
        messages.success(request, f"Imported as {state}: {result.summary()}.")
        if result.bad_emails:
            messages.warning(
                request,
                f"{len(result.bad_emails)} address(es) weren't valid, including: "
                + ", ".join(result.bad_emails[:10]))
        return redirect("wagtailsnippets_prblm_mailer_subscriber:list")

    return render(request, "prblm_mailer/import_subscribers_map.html", {
        "newsletter": newsletter,
        "token": token,
        "headers": headers,
        "mapping": result.mapping if result else mapping,
        "fields": [
            ("email", "Email address", True),
            ("name", "Name", False),
            ("first_name", "First name", False),
            ("last_name", "Last name", False),
            ("groups", "Groups", False),
            ("status", "Status", False),
        ],
        "samples": sample_rows(rows),
        "row_count": len(rows),
        "preview": result,
        "confirmed": confirmed,
    })
