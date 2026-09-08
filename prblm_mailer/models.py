"""Newsletter models — snippet-based.

A newsletter is a **Broadcast**: a subject + a body of email-safe MJML blocks,
written and sent from the Wagtail admin (Snippets → Newsletters). It is not a page.

Recipients are chosen on the send page: every confirmed subscriber by default, or a
narrower set of groups. Subscribers, double opt-in and unsubscribe are
django-newsletter's job; delivery and bounce handling are Mailgun's (via anymail).

Click and open tracking come from Mailgun's own tracking, delivered to the Anymail
webhook and stored as `EngagementEvent` rows — we run no redirect/pixel endpoint of
our own.
"""
from django.db import models
from django.utils import timezone

from wagtail.admin.panels import FieldPanel, HelpPanel
from wagtail.fields import StreamField
from wagtail.models import PreviewableMixin

from . import blocks as email_blocks

# Substrings that mark an unsubscribe link (django-newsletter's confirm URL and our
# one-click route both contain "/unsubscribe/"). Clicks on these are list churn, not
# engagement, so engagement_stats excludes them.
UNSUBSCRIBE_URL_MARKERS = ("/unsubscribe/",)


class Broadcast(PreviewableMixin, models.Model):
    """One newsletter email. Draft it, then send it to all confirmed subscribers."""

    STATUS_DRAFT = "draft"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    subject = models.CharField(max_length=255, help_text="The email subject line.")
    # Required: an empty newsletter is never something anyone meant to send.
    body = StreamField(
        email_blocks.email_body_blocks(),
        help_text="Build the newsletter from email blocks. Use the + button to add one.",
    )

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Filled in when sent — a record of what actually went out.
    sent_html = models.TextField(blank=True)
    emails_sent = models.PositiveIntegerField(default=0)
    emails_failed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    # Who it went to, frozen at send time (the live M2M can be edited later).
    sent_audience = models.CharField(max_length=500, blank=True)

    # Who it goes to — set from the send page. Nothing selected = everyone confirmed.
    send_to_tags = models.ManyToManyField(
        "prblm_mailer.SubscriberTag", blank=True, related_name="broadcasts",
        verbose_name="Groups to send to",
    )
    include_ungrouped = models.BooleanField(
        default=False, verbose_name="Subscribers with no group",
    )

    panels = [
        FieldPanel("subject"),
        FieldPanel("body"),
        HelpPanel(
            "<strong>Save</strong> keeps a draft. <strong>Save &amp; send</strong> saves and "
            "opens the send page, where you choose which groups it goes to, preview it, "
            "send a test to yourself, and see the exact recipient count before sending."
        ),
    ]

    class Meta:
        verbose_name = "newsletter"
        verbose_name_plural = "newsletters"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.get_status_display()})"

    @property
    def is_sent(self):
        return self.status == self.STATUS_SENT

    def serve_preview(self, request, mode_name):
        """Live preview: the real compiled email (MJML → HTML) in the editor panel."""
        from django.http import HttpResponse
        from .sending import render_email_html

        try:
            return HttpResponse(render_email_html(self))
        except Exception as exc:  # noqa: BLE001 — a half-written block must not 500 the preview
            return HttpResponse(
                f"<p style='font-family:sans-serif;padding:2rem;color:#b00'>"
                f"Preview unavailable: {exc}</p>"
            )

    def duplicate(self):
        """A fresh draft copy — same subject/body, none of the sent state."""
        copy = Broadcast.objects.create(
            subject=f"{self.subject} (copy)",
            body=self.body,
            include_ungrouped=self.include_ungrouped,
        )
        copy.send_to_tags.set(self.send_to_tags.all())  # M2M needs a pk first
        return copy

    def sent_audience_rows(self):
        """The frozen audience as (group, answer) rows, for a table.

        Splits the `sent_audience` snapshot on ", " — safe because a dropdown answer
        can't contain a comma (Wagtail splits choices on commas). Returns [] for an
        "everyone" or unrecorded send.
        """
        label = (self.sent_audience or "").strip()
        if not label or label == "everyone":
            return []
        rows = []
        for part in label.split(", "):
            if part == "no group":
                rows.append(("(no group)", "Signed up without answering a grouping question"))
            elif ": " in part:
                group, answer = part.split(": ", 1)
                rows.append((group, answer))
            else:
                rows.append((part, ""))
        return rows

    def mark_sent(self, *, html, sent, failed):
        from . import audience

        self.status = self.STATUS_SENT
        self.sent_html = html
        self.emails_sent = sent
        self.emails_failed = failed
        # Freeze the audience description now, before any group can be edited.
        self.sent_audience = audience.describe(self)[:500]
        self.sent_at = timezone.now()
        self.save(update_fields=[
            "status", "sent_html", "emails_sent", "emails_failed",
            "sent_audience", "sent_at", "updated_at",
        ])

    # --- Engagement (clicks + opens) -----------------------------------------
    def engagement_stats(self, top=10):
        """Click/open totals for the send page. Never counts the unsubscribe link.

        `unique` counts distinct *subscribers*, so one person clicking a link five
        times is one person — that's what a rate should mean. Events we couldn't
        attribute to anyone (an email sent before tracking went live) still count
        toward the total but not toward unique, and are reported separately rather
        than quietly inflating either number.

        Unsubscribe-link clicks are excluded from every figure: Mailgun rewrites
        that link despite `clicktracking="off"`, and counting somebody leaving as
        engagement would make the numbers say the opposite of what happened.
        """
        from django.db.models import Count, Q

        unsub = Q()
        for marker in UNSUBSCRIBE_URL_MARKERS:
            unsub |= Q(url__contains=marker)

        events = self.engagement.all()
        clicks = events.filter(kind=EngagementEvent.KIND_CLICK).exclude(unsub)
        opens = events.filter(kind=EngagementEvent.KIND_OPEN)

        def unique(queryset):
            return (queryset.filter(subscription__isnull=False)
                    .values("subscription").distinct().count())

        def rate(unique_count):
            return round(unique_count / self.emails_sent * 100, 1) if self.emails_sent else None

        clicks_unique, opens_unique = unique(clicks), unique(opens)
        return {
            "clicks_total": clicks.count(),
            "clicks_unique": clicks_unique,
            "clicks_unattributed": clicks.filter(subscription__isnull=True).count(),
            "click_rate": rate(clicks_unique),
            "opens_total": opens.count(),
            "opens_unique": opens_unique,
            "open_rate": rate(opens_unique),
            "top_urls": list(
                clicks.values("url")
                .annotate(total=Count("id"), people=Count("subscription", distinct=True))
                .order_by("-total", "url")[:top]
            ),
        }

    def _engagement_count(self, kind, annotation):
        """A click/open count for the listing — using the viewset's annotation if present."""
        count = getattr(self, annotation, None)
        if count is None:
            count = self.engagement.filter(kind=kind).count()
        return count if self.is_sent else "—"

    def clicks_column(self):
        return self._engagement_count(EngagementEvent.KIND_CLICK, "click_total")
    clicks_column.short_description = "Clicks"

    def opens_column(self):
        return self._engagement_count(EngagementEvent.KIND_OPEN, "open_total")
    opens_column.short_description = "Opens"


from newsletter.models import Subscription


class SubscriberTag(models.Model):
    """One *(group, value)* pair a subscriber can hold — e.g. Interest → peer-review.

    Groups come from the signup form (a field ticked "use for grouping"). Storing the
    answer here — not reading the form at send time — is what makes editing that form
    field later safe. Grouping is an optional feature: sites without such a form
    simply never create tags.

    A separate model because `Subscription` belongs to django-newsletter; an M2M from
    our table adds groups without touching its schema.
    """

    group_name = models.CharField(
        max_length=80, help_text="The group this answer belongs to, e.g. 'Interest'.",
    )
    # The match key: "I'd like to subscribe" and "I'd Like To Subscribe" are one tag.
    value_slug = models.SlugField(max_length=80)
    # The wording as first seen, for display.
    value_label = models.CharField(max_length=160)

    subscriptions = models.ManyToManyField(
        Subscription, related_name="tags", blank=True,
    )

    class Meta:
        unique_together = [("group_name", "value_slug")]
        ordering = ["group_name", "value_label"]
        verbose_name = "subscriber group"
        verbose_name_plural = "subscriber groups"

    def __str__(self):
        return f"{self.group_name}: {self.value_label}"


class Subscriber(Subscription):
    """A read-only Wagtail-admin view over django-newsletter's Subscription.

    A proxy model (same rows as Subscription) that adds a plain-English status. The
    subscribe/confirm/unsubscribe logic stays entirely django-newsletter's.
    """

    class Meta:
        proxy = True
        verbose_name = "subscriber"
        verbose_name_plural = "subscribers"

    @property
    def status(self):
        if self.unsubscribed:
            return "Unsubscribed"
        if self.subscribed:
            return "Confirmed"
        return "Pending confirmation"

    def status_label(self):
        colours = {
            "Confirmed": "#1a9f5a",
            "Pending confirmation": "#b7791f",
            "Unsubscribed": "#9aa0a6",
        }
        from django.utils.html import format_html
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
            'font-size:12px;font-weight:600;color:#fff;background:{}">{}</span>',
            colours.get(self.status, "#6a6a6a"), self.status,
        )
    status_label.short_description = "Status"

    def groups_label(self):
        """The subscriber's groups as pills — read-only."""
        from django.utils.html import format_html, format_html_join

        tags = self.tags.all()
        if not tags:
            return format_html('<span style="color:#9aa0a6">—</span>')
        return format_html_join(
            " ", '<span style="display:inline-block;padding:2px 9px;border-radius:10px;'
                 'font-size:12px;background:#eceef1;color:#3a3a3a;white-space:nowrap">'
                 '{}: <strong>{}</strong></span>',
            ((t.group_name, t.value_label) for t in tags),
        )
    groups_label.short_description = "Groups"


class EmailEvent(models.Model):
    """Bounces/complaints from Mailgun webhooks — why someone was auto-dropped."""

    email = models.EmailField()
    event = models.CharField(max_length=32)  # bounced / complained / unsubscribed
    reason = models.TextField(blank=True)
    broadcast = models.ForeignKey(
        Broadcast, on_delete=models.SET_NULL, null=True, blank=True, related_name="events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["email", "event"])]
        ordering = ["-created_at"]


class EngagementEvent(models.Model):
    """One row per Mailgun click or open on a sent newsletter.

    A row per event (not a counter or a boolean) so both "total" and "unique people"
    are answerable, plus a timeline — and so the data can later feed segmentation.
    Clicks and opens share this table, told apart by `kind`; a click also stores the
    URL, an open leaves it blank.
    """

    KIND_CLICK = "clicked"
    KIND_OPEN = "opened"
    KIND_CHOICES = [(KIND_CLICK, "Click"), (KIND_OPEN, "Open")]

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    broadcast = models.ForeignKey(
        Broadcast, on_delete=models.CASCADE, related_name="engagement",
    )
    # SET_NULL, not CASCADE: deleting a subscriber must not silently rewrite the
    # totals of newsletters already sent.
    subscription = models.ForeignKey(
        "newsletter.Subscription", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="engagement",
    )
    url = models.URLField(max_length=2000, blank=True)   # clicks only
    at = models.DateTimeField()
    # Mailgun retries webhook delivery until it gets a 200, so the same event can
    # arrive several times. Unique on Mailgun's own event id stops a double count.
    mailgun_event_id = models.CharField(max_length=255, unique=True)
    # Personal data: blanked when a subscriber is deleted (SET_NULL alone would leave
    # an identifying IP behind) — see scrub_engagement_ips_on_delete.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["broadcast", "kind", "at"]),
            models.Index(fields=["broadcast", "kind", "subscription"]),
        ]
        ordering = ["-at"]
        verbose_name = "engagement event"

    def __str__(self):
        who = self.subscription.email if self.subscription else "unknown"
        return f"{who} {self.kind} {self.url}".strip()
