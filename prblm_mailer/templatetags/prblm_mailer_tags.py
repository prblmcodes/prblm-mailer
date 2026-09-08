"""Template tags for pages this package styles but does not render.

django-newsletter's public pages (confirm, unsubscribe, activated…) are its own
views with its own context, so there is no hook to pass settings in — a tag is how
the shared page shell reads `PRBLM_MAILER`.
"""
from django import template

from ..conf import get_setting

register = template.Library()


@register.simple_tag
def mailer_setting(name, default=""):
    """One `PRBLM_MAILER` value, or `default` when it is unset/blank."""
    return get_setting(name) or default
