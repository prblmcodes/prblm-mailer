# Changelog

All notable changes, newest first. Each version is a git tag; what to do when moving between
versions is in [docs/upgrading.md](docs/upgrading.md).

## 0.6.0b1 — 2026-11-26

**Wagtail 8 and Django 6.1 support.** Supported range is now Wagtail 6–8, Django 5.0–6.1 and
django-newsletter 1.2–1.3.

### Fixed
- The Subscribers admin crashed (HTTP 500) on Django 6 for any subscriber with no groups.
- `console` and `local` delivery crashed once a site defined Django 6.1's `MAILERS` — breaking
  test sends, newsletters and confirmation emails in local development. `mailgun` mode was not
  affected.
- On Wagtail 8, WebP and AVIF images were sent as-is, and Outlook can't display them. All image
  blocks now send them as PNG; other formats are unchanged.

### Changed
- No more use of the mail APIs Django 6.1 deprecated (`get_connection()`, `connection=`), on any
  Django version.
- `local` mode no longer picks up the site's `EMAIL_*` login or TLS settings; it connects to
  `LOCAL_SMTP_HOST:LOCAL_SMTP_PORT` without authentication.
- New `{% email_image %}` template tag for email-safe image renditions.
- Releases are published automatically when a version tag is pushed, after the tests pass on
  three Wagtail/Django pairs.

## 0.5.1b1 — 2026-10-21

### Fixed
- Mapping a CSV column to **Groups** did nothing when the column held plain values (`Essex`
  rather than `Location: Essex`). Plain values are now filed under the column's own name, and
  the preview reports how many rows carry a group.

## 0.5.0b1 — 2026-10-21

### Added
- **Subscribe date on import.** Map the column holding when people originally joined. Reads
  ISO, `dd/mm/yyyy`, `mm/dd/yyyy`, spelled-out dates and unix timestamps, and works out
  day-first versus month-first from the file itself.

### Fixed
- Imported subscribers, including confirmed ones, had no subscribe date.

## 0.4.0b1 — 2026-10-21

### Added
- **Import a CSV from anywhere.** The email column is found by its header or by its contents;
  the delimiter and header row are detected; and a preview step shows the detected columns,
  sample rows and exact counts before anything is written. Any column can be corrected.
- Rows marked unsubscribed, cleaned, bounced or complained are skipped, so importing another
  tool's export can't re-add people who left.
- `--map FIELD=COLUMN` for `import_subscribers`.

### Fixed
- A CSV whose email column wasn't literally called `email` imported nobody and reported only
  "0 new".

## 0.3.0b1 — 2026-09-29

### Added
- **Social links** block, with PNG icons that work in every mail client (Gmail strips SVG).
- **Two columns (text + text)** block, each card with its own colours and button.
- **Two images** block with an adjustable split and captions.

Needs `migrate` and `collectstatic`.

## 0.2.0b1 — 2026-09-08

### Added
- **Conditional signup:** a checkbox field marked *Use as the newsletter opt-in* decides whether
  a form submitter joins the list.
- **Styled confirmation email and public pages**, all overridable. The confirm page hides the
  activation code, recognises a reused link, and offers *Deny subscription*.
- **CSV import and export buttons** in the Subscribers admin.
- **Startup checks** `W002`, `W003` and `W004`.
- The Site domain is corrected from `WAGTAILADMIN_BASE_URL` while it is still `example.com`.

### Changed
- The Subscribers listing is read-only (no Edit button).

Hosts using `AbstractGroupingFormField` need `makemigrations` for their own app.

## 0.1.0b1 — 2026-09-08

First release: newsletters built from MJML blocks in the Wagtail admin, double opt-in through
django-newsletter, groups, four delivery modes, Mailgun sending through Anymail, open and click
tracking, bounce handling, CSV commands, and the `mailgun_doctor` and `simulate_mailgun_click`
commands.
