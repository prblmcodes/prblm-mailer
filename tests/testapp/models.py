"""Concrete form page using the plugin's abstract bases — for the test suite only."""
from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import InlinePanel
from wagtail.contrib.forms.models import AbstractEmailForm

from prblm_mailer.form_pages import AbstractGroupingFormField, NewsletterFormMixin


class GroupingFormField(AbstractGroupingFormField):
    page = ParentalKey(
        "testapp.NewsletterFormPage", related_name="form_fields", on_delete=models.CASCADE,
    )


class NewsletterFormPage(NewsletterFormMixin, AbstractEmailForm):
    content_panels = AbstractEmailForm.content_panels + [
        InlinePanel("form_fields", label="Form fields"),
        *NewsletterFormMixin.newsletter_panels,
    ]
