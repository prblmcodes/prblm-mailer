# Upgrading

## Every upgrade

1. Change the tag in your requirements:

   ```
   prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.6.1b1
   ```

2. Install, migrate and check:

   ```bash
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --noinput     # where you serve static files
   python manage.py check
   ```

3. Read the notes below for **every version between yours and the new one** — skipping
   versions is fine as long as you follow each step.

You can see which version you're on with `pip show prblm-mailer`. The full list of changes is
in the [CHANGELOG](../CHANGELOG.md).

---

## To 0.6.1b1 (from 0.6.0b1)

A bug fix: the Subscribers admin's add URL no longer crashes when opened directly. Nothing to
do.

## To 0.6.0b1 (from 0.5.x)

Adds **Wagtail 8** and **Django 6.0/6.1**, and django-newsletter 1.3. Nothing to change in your
code or database.

- **If you use Django 6.1's `MAILERS`:** make Mailgun the default mailer —
  `MAILERS = {"default": {"BACKEND": "anymail.backends.mailgun.EmailBackend"}}` — instead of
  `EMAIL_BACKEND`. See [Django 6.1 `MAILERS`](delivery-and-mailgun.md#django-61-mailers).
- **`local` mode no longer uses your `EMAIL_*` login or TLS settings.** It connects to
  `LOCAL_SMTP_HOST:LOCAL_SMTP_PORT` without authentication, which is what mailcrab and mailpit
  expect. If your local catcher needs a login, it won't get one any more.
- **WebP and AVIF images** are now sent as PNG on every Wagtail version (Wagtail 8 had stopped
  converting them).

Upgrading Django or Wagtail at the same time? Upgrade the plugin first: 0.5.x and older refuse
Django 6 and Wagtail 8, and crash on them if forced.

## To 0.5.0b1 / 0.5.1b1 (from 0.4.x)

CSV import improvements only — subscribe dates and groups from plain columns. Nothing to do.

## To 0.4.0b1 (from 0.3.x)

The new CSV importer with column detection and a preview step. Nothing to do.

## To 0.3.0b1 (from 0.2.x)

Adds the Social links, Two columns (text + text) and Two images blocks.

- Run **`migrate`** (the newsletter body gains the new blocks).
- Run **`collectstatic`** where you serve static files — the social icons are static images,
  and email clients load them from your site.

## To 0.2.0b1 (from 0.1.x)

Adds conditional signup (the opt-in checkbox), styled public pages, admin CSV import/export
and the startup checks.

- If your form fields inherit **`AbstractGroupingFormField`**, it gains a `use_for_optin`
  field, so create a migration for **your** app:

  ```bash
  python manage.py makemigrations <your_app>
  python manage.py migrate
  ```

- If you list apps by hand instead of using `with_required_apps`, put `prblm_mailer`
  **before** `newsletter`, or the styled pages won't be used.
- Run `python manage.py check` and fix anything it reports — the checks are new in this
  version.

Existing behaviour is unchanged: a form without an opt-in checkbox subscribes every
submission, as before. Templates you already override (`newsletter/message/subscribe.html`,
`newsletter/common.html`) still take priority.
