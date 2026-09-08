"""Optional helpers that turn a Wagtail form-builder page into a newsletter signup.

Two abstract bases the host subclasses — one for the page, one for its form fields.
Adopting them is two one-word base-class swaps; the "collect subscribers" toggle,
the per-field grouping controls, and the double-opt-in call all come for free.

    from django.db import models
    from modelcluster.fields import ParentalKey
    from wagtail.admin.panels import InlinePanel
    from wagtail.contrib.forms.models import AbstractEmailForm

    from prblm_mailer.form_pages import AbstractGroupingFormField, NewsletterFormMixin

    class FormField(AbstractGroupingFormField):
        page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)

    class FormPage(NewsletterFormMixin, AbstractEmailForm):
        content_panels = AbstractEmailForm.content_panels + [
            InlinePanel("form_fields", label="Form fields"),
            *NewsletterFormMixin.newsletter_panels,
        ]

Nothing here is required to use the package — a host with its own form can just call
`prblm_mailer.subscriptions.subscribe_from_form()` directly (the "manual" path in the
README). These bases only save the boilerplate.

Note: the mixin must come **before** the form base in the bases list, so its
`process_form_submission` runs and then delegates to the form base via `super()`.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import models

from wagtail.admin.panels import FieldPanel
from wagtail.contrib.forms.models import AbstractFormField

from .segments import CHOICE_FIELD_TYPES

logger = logging.getLogger(__name__)


class AbstractGroupingFormField(AbstractFormField):
    """A form-builder field that can be marked as a subscriber-grouping field.

    Ticking "use for grouping" turns this field's answer into a `SubscriberTag`
    when someone submits the form — so a "Which instrument?" dropdown becomes the
    Instrument group. The plugin reads these two attributes by duck-typing (see
    `segments.grouping_specs`), so a host field model that simply defines them by
    hand works just as well as subclassing this.
    """

    use_for_grouping = models.BooleanField(
        default=False,
        help_text="Turn this field's answer into a subscriber group, for targeting newsletters.",
    )
    group_name = models.CharField(
        max_length=80, blank=True,
        help_text="Name of the group (defaults to the field's label).",
    )

    # AbstractFormField defines its own `panels`; extend so the new fields are editable.
    panels = AbstractFormField.panels + [
        FieldPanel("use_for_grouping"),
        FieldPanel("group_name"),
    ]

    @property
    def resolved_group_name(self):
        return self.group_name or self.label

    def clean(self):
        super().clean()
        # Grouping only makes sense on fields with a fixed set of answers — otherwise
        # every submission mints a new group. Catch it in the editor, not at send time.
        if self.use_for_grouping and self.field_type not in CHOICE_FIELD_TYPES:
            raise ValidationError({
                "use_for_grouping": (
                    "Grouping only works on choice fields "
                    "(dropdown, radio, checkboxes, multiselect). "
                    f"“{self.label or 'this field'}” is a {self.field_type} field."
                )
            })

    class Meta(AbstractFormField.Meta):
        abstract = True


class NewsletterFormMixin(models.Model):
    """Add a "collect newsletter subscribers" toggle + double opt-in to a form page.

    Combine with any Wagtail form base (AbstractEmailForm, AbstractForm, a captcha
    form). When the toggle is on, every submission is offered to the newsletter
    list with double opt-in; grouping answers ride along automatically. When it's
    off, the page behaves like an ordinary form.
    """

    collect_newsletter_subscribers = models.BooleanField(
        default=False,
        verbose_name="Collect newsletter subscribers",
        help_text="Add people who submit this form to the newsletter list (double opt-in). "
                  "The form must include an email field.",
    )

    # For the host to splice into its content_panels.
    newsletter_panels = [FieldPanel("collect_newsletter_subscribers")]

    class Meta:
        abstract = True

    def process_form_submission(self, form):
        # Store the submission (and, for AbstractEmailForm, send the notification)
        # exactly as normal first — subscribing is an addition, never a replacement.
        submission = super().process_form_submission(form)
        if self.collect_newsletter_subscribers:
            # Never raises; refuses (and logs) if the submission has no email address,
            # so a form ticked-on but missing an email field can't create junk rows.
            from .subscriptions import subscribe_from_form

            subscribe_from_form(form.cleaned_data, page=self)
        return submission
