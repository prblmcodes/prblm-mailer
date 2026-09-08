"""Wagtail-admin views: the dedicated send page, the confirm step, and duplicate.

A separate page from the snippet editor so "write it" and "send it" stay distinct.
Sending is synchronous — one Mailgun batch call covers 1000 recipients.
"""
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


@require_admin_access
def import_subscribers(request):
    """Upload a CSV of subscribers. Same rules as the management command.

    Consent is the whole story here: rows land pending unless the uploader
    explicitly states they already hold consent, and no opt-in emails are sent
    either way (see `csv_io.import_rows`).
    """
    import io

    from django.http import Http404

    from .csv_io import import_rows, resolve_newsletter

    newsletter = resolve_newsletter()
    if newsletter is None:
        raise Http404("No newsletter list configured.")

    if request.method == "POST":
        upload = request.FILES.get("csv_file")
        if upload is None:
            messages.error(request, "Choose a CSV file to import.")
            return redirect(reverse("prblm_mailer_import_subscribers"))

        confirmed = request.POST.get("confirmed") == "on"
        try:
            text = io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline="")
            created, updated, skipped, bad = import_rows(
                text, newsletter, confirmed=confirmed)
        except UnicodeDecodeError:
            messages.error(request, "That file isn't UTF-8 text — export it as CSV and retry.")
            return redirect(reverse("prblm_mailer_import_subscribers"))
        except Exception as exc:  # noqa: BLE001 — a bad CSV must not 500 the admin
            messages.error(request, f"Import failed: {exc}")
            return redirect(reverse("prblm_mailer_import_subscribers"))

        state = "confirmed" if confirmed else "pending (they must still confirm)"
        messages.success(
            request,
            f"Imported as {state}: {created} new, {updated} already on the list, "
            f"{skipped} skipped.",
        )
        if bad:
            messages.warning(request, "Skipped invalid addresses: " + ", ".join(bad[:10]))
        return redirect("wagtailsnippets_prblm_mailer_subscriber:list")

    return render(request, "prblm_mailer/import_subscribers.html", {"newsletter": newsletter})
