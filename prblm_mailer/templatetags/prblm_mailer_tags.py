"""Template tags for pages this package styles but does not render, and for email images.

django-newsletter's public pages (confirm, unsubscribe, activated…) are its own
views with its own context, so there is no hook to pass settings in — a tag is how
the shared page shell reads `PRBLM_MAILER`.
"""
import os

from django import template

from ..conf import get_setting

register = template.Library()

# Source formats a mail client may not display. Wagtail ≤7 turned both into PNG on its
# own; Wagtail 8 keeps them as they are, and Outlook desktop shows WebP as a blank box.
_NOT_EMAIL_SAFE = {".webp", ".avif"}


@register.simple_tag
def mailer_setting(name, default=""):
    """One `PRBLM_MAILER` value, or `default` when it is unset/blank."""
    return get_setting(name) or default


@register.filter
def get_item(mapping, key):
    """`mapping[key]`, for templates that have to look a value up by a variable.

    Used by the import mapping screen, whose columns and dropdown names both come
    from the uploaded file rather than from anything we can name in advance.
    """
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.simple_tag
def email_image(image, spec):
    """A rendition of `image` at `spec` that every mail client can display.

    WebP/AVIF become PNG (lossless, keeps transparency — what Wagtail ≤7 did for us);
    everything else keeps the format it was uploaded in, so a JPEG photo stays small
    and a transparent PNG logo stays transparent. Decided by file extension, which
    Wagtail checks against the real format on upload.
    """
    from wagtail.images.shortcuts import get_rendition_or_not_found

    if os.path.splitext(image.file.name)[1].lower() in _NOT_EMAIL_SAFE:
        spec = f"{spec}|format-png"
    return get_rendition_or_not_found(image, spec)
