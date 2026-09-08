from django.apps import AppConfig


class PrblmMailerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "prblm_mailer"
    verbose_name = "Newsletter"

    def ready(self):
        from . import checks  # noqa: F401 — registers startup setting checks
        from . import signals  # noqa: F401 — connects the Mailgun webhook receiver
