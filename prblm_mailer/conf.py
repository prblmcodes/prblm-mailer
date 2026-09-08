"""Package settings, with defaults.

The host site sets only what differs, in a single ``PRBLM_MAILER`` dict. Everything
else falls back to a default here — so a fresh install works with almost no config.
Never import beMore or any host app from this module; the package must stand alone.

    from prblm_mailer.conf import get_setting
    brand = get_setting("BRAND_COLOR")
"""
from django.conf import settings

# How a send is delivered. One switch, four modes:
#   "dry_run" — log stats only, send nothing (safe default in DEBUG)
#   "console" — print the full rendered email to the terminal, per recipient
#   "local"   — send to a local inbox (mailcrab/mailpit) over SMTP
#   "mailgun" — real send via Anymail's Mailgun backend
DELIVERY_MODES = ("dry_run", "console", "local", "mailgun")

# Defaults. Override any of these via settings.PRBLM_MAILER = {...}.
DEFAULTS = {
    "NEWSLETTER_SLUG": "main",        # the django-newsletter list this site sends to
    "FROM_EMAIL": "",                 # required in real use; blank fails loudly at send
    "FROM_NAME": "",
    "REPLY_TO": "",
    "BRAND_COLOR": "#2b6cb0",         # default button colour; each site overrides
    # Log the message instead of sending. Defaults to DEBUG so dev/staging is safe.
    # Kept as a back-compat alias for DELIVERY="dry_run".
    "DRY_RUN": None,                  # None -> resolved to settings.DEBUG at read time
    # None -> resolved at read time: dry_run when DRY_RUN/DEBUG is on, else mailgun.
    "DELIVERY": None,
    # Where DELIVERY="local" sends. Defaults to mailcrab/mailpit's standard SMTP port.
    "LOCAL_SMTP_HOST": "localhost",
    "LOCAL_SMTP_PORT": 1025,
}

# Note: the Mailgun region + keys live in the host's standard ANYMAIL dict (set
# MAILGUN_API_URL there to the EU endpoint). Footer content (name, address,
# contact) is authored per-newsletter in the Footer block, not a setting.


def get_setting(name):
    """One package setting: the host's PRBLM_MAILER override, else the default."""
    configured = getattr(settings, "PRBLM_MAILER", {}) or {}
    if name in configured:
        return configured[name]
    default = DEFAULTS[name]
    if name == "DRY_RUN" and default is None:
        return bool(getattr(settings, "DEBUG", False))
    if name == "DELIVERY" and default is None:
        # No explicit DELIVERY: fall back to the DRY_RUN/DEBUG behaviour, so an
        # existing install (or a dev machine) stays log-only without new config.
        return "dry_run" if get_setting("DRY_RUN") else "mailgun"
    return default
