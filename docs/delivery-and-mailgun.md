# Delivery modes and Mailgun

One setting, `PRBLM_MAILER["DELIVERY"]`, decides where every email the plugin sends ends up.
That makes it safe to develop with a real subscriber list: nothing reaches a real inbox until
you switch to `mailgun`.

- [The four modes](#the-four-modes)
- [What `DELIVERY` covers — and the one email it doesn't](#what-delivery-covers)
- [A local inbox](#a-local-inbox)
- [Going live with Mailgun](#going-live-with-mailgun)
- [Django 6.1 `MAILERS`](#django-61-mailers)
- [Sending limits](#sending-limits)

---

## The four modes

| Mode | What happens | Needs |
|---|---|---|
| `dry_run` | Logs the recipient count and size. Sends nothing. | — |
| `console` | Prints each full rendered email in the server's terminal. | — |
| `local` | Sends to a local inbox such as mailcrab or mailpit, so you see it like a real email. | A local inbox |
| `mailgun` | Real sending through Mailgun. | A Mailgun account |

If `DELIVERY` isn't set, it is `dry_run` when `DEBUG` is on and `mailgun` otherwise.

`console` and `local` send **one email per recipient** and fill in each person's details
(name, unsubscribe link) themselves, so what you see is the finished email. `mailgun` sends in
batches of up to 1,000 and lets Mailgun personalise each copy.

Only `mailgun` gives you **open and click tracking**, because Mailgun is what rewrites links
and adds the open pixel. Links in a `console` or `local` email are plain, and clicking them
records nothing. See [tracking](tracking.md).

## What `DELIVERY` covers

`DELIVERY` controls three kinds of email:

1. newsletters,
2. test sends,
3. the **double opt-in confirmation email** a new subscriber receives.

So with `DELIVERY = "local"`, confirmation emails land in your local inbox too, without
touching Django's own email settings.

The one email it does **not** control is a Wagtail form page's own *"someone filled in your
form"* notification. That is Wagtail's, and goes through Django's normal email setup. To catch
it in the same local inbox:

```python
# Django 6.0 and earlier
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST, EMAIL_PORT = "localhost", 1025

# Django 6.1+ with MAILERS
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                       "OPTIONS": {"host": "localhost", "port": 1025}}}
```

## A local inbox

[mailcrab](https://github.com/tweedegolf/mailcrab) catches everything sent to it and shows it
in a web page. With Docker:

```bash
docker run --rm -p 1080:1080 -p 1025:1025 marlonb/mailcrab:latest
# read mail at http://localhost:1080 — add -d to run it in the background
```

```python
PRBLM_MAILER = {**PRBLM_MAILER, "DELIVERY": "local"}
```

mailpit and MailHog work the same way. The plugin sends to `localhost:1025` by default; change
it with `LOCAL_SMTP_HOST` and `LOCAL_SMTP_PORT`. If nothing is listening there, the send stops
with a message saying so rather than failing silently.

The `console` and `local` modes build their own connection from those two settings. They never
use your `EMAIL_*` or `MAILERS` configuration, so a local test can't accidentally go out
through your real mail server with your real login.

## Going live with Mailgun

**1. Configure Anymail** with your Mailgun keys. Keep secrets in environment variables, never
in code:

```python
import os

EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"   # Django 6.1+: see MAILERS below

ANYMAIL = {
    "MAILGUN_API_KEY": os.environ["MAILGUN_API_KEY"],
    "MAILGUN_SENDER_DOMAIN": "mg.example.com",
    "MAILGUN_API_URL": "https://api.eu.mailgun.net/v3",    # EU account; US is https://api.mailgun.net/v3
    "MAILGUN_WEBHOOK_SIGNING_KEY": os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"],
    "WEBHOOK_SECRET": os.environ["ANYMAIL_WEBHOOK_SECRET"],  # "user:pass" for the webhook URL
}
```

The API URL must match the region your Mailgun account is in — an EU account can't be reached
through the US URL, or the other way round.

**2. Switch delivery** and make sure the sender is set:

```python
PRBLM_MAILER = {
    **PRBLM_MAILER,
    "DELIVERY": "mailgun",
    "FROM_EMAIL": "news@mg.example.com",   # an address on your Mailgun sending domain
}
WAGTAILADMIN_BASE_URL = "https://your-site.com"
```

**3. Set up the webhooks** so bounces unsubscribe people automatically and opens/clicks are
counted — see [tracking](tracking.md#setting-it-up).

**4. Check everything end to end:**

```bash
python manage.py mailgun_doctor
```

It works through four layers — your Django settings, the Mailgun sending domain (state, DNS,
tracking switches), the registered webhooks, and whether your webhook URL answers — and marks
each check ✓ or ✗ with a hint. Add `--probe` to also post a signed test event to your own
webhook. It needs the `requests` package.

> The region check currently expects the **EU** endpoint, so on a US account its *API region*
> line shows ✗ even when the URL is right. Ignore that one line if your account is in the US.

**5. Send yourself a real test** from the Send page, then send for real.

## Django 6.1 `MAILERS`

Django 6.1 replaces `EMAIL_BACKEND` and the other `EMAIL_*` settings with `MAILERS`. If your
site uses it, make Mailgun the **default** mailer instead of setting `EMAIL_BACKEND` (Django
refuses to start with both):

```python
MAILERS = {"default": {"BACKEND": "anymail.backends.mailgun.EmailBackend"}}
```

`mailgun` mode always sends through the site's default mailer, however it is defined. The other
three modes don't use it at all.

## Sending limits

Sending happens inside the request when you press **Send now**: one Mailgun call per 1,000
recipients. That is fine into the low thousands of subscribers. There is no background queue
yet, so very large lists may hit your web server's request timeout.
