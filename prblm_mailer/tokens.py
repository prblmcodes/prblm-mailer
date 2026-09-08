"""Signed unsubscribe token — its own module so `sending` and `views` share it
without importing each other."""
from django.core import signing

SALT = "prblm_mailer.oneclick-unsubscribe"

# Two years. Long enough nobody hits it on a genuinely old newsletter; short enough
# that a forwarded email can't hand out perpetual power to unsubscribe someone.
ONECLICK_MAX_AGE = 60 * 60 * 24 * 365 * 2


def oneclick_token(subscription):
    """A signed, tamper-proof token identifying a subscription (its pk)."""
    return signing.dumps(subscription.pk, salt=SALT)
