"""prblm-mailer — a self-hosted newsletter platform for Wagtail.

`with_required_apps` is safe to call from a settings module (it only manipulates a
list of strings — no Django imports), so keep this module import-light.
"""

# The apps prblm-mailer needs in INSTALLED_APPS: itself plus its runtime deps.
_REQUIRED_APPS = [
    "prblm_mailer",
    "newsletter",
    "anymail",
    "sorl.thumbnail",
    "django.contrib.sites",
]


def required_apps():
    """The apps prblm-mailer needs in INSTALLED_APPS, as a list."""
    return list(_REQUIRED_APPS)


def with_required_apps(installed_apps):
    """Return `installed_apps` plus any of prblm-mailer's apps not already present.

    De-duplicates, so it's safe when the host already lists some of them (e.g. a
    project that already uses `anymail` or `django.contrib.sites`). Use in settings:

        from prblm_mailer import with_required_apps
        INSTALLED_APPS = with_required_apps(INSTALLED_APPS)
    """
    apps = list(installed_apps)
    for app in _REQUIRED_APPS:
        if app not in apps:
            apps.append(app)
    return apps
