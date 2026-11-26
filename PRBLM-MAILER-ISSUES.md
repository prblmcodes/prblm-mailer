# prblm-mailer on Wagtail 8.1 + Django 6.1: what breaks

> **Resolved in 0.6.0b1.** Every item below is fixed, including the deprecations (§5) and a fifth
> image template the report missed (`email_two_image.html`). Supported range is now Wagtail 6–8,
> Django 5.0–6.1, django-newsletter 1.2–1.3. Pinned by `tests/test_compat.py`.

Found while upgrading breakingbeats (branch `upgrade/wagtail-8.1-django-6.1`, 2026-11-26).

- **Tested with:** prblm-mailer `v0.2.0b1`, installed with its version limits overridden, on Django 6.1.3, Wagtail 8.1, django-anymail 15.3 and Python 3.12.
- **Latest tag:** every issue below is still present in `v0.5.1b1`, checked against the source on GitHub.
- **How it was tested:** the old and new stacks ran side by side on copies of the staging database, and the results were compared. See "How this was found" at the end.

## 1. Version limits block the install (blocker)

`pyproject.toml`:
```
"Django>=5.0,<5.3",
"wagtail>=6.0,<8",
"django-newsletter>=1.2,<1.3",
```
pip refuses Django 6.x and Wagtail 8.x, so the site can't be installed or deployed until a release widens these limits.

django-newsletter 1.3.0 (2026-10-28) is the first release that supports Django 6.1, and it adds a `NEWSLETTER_MAILER` setting. The site currently still runs 1.2.1, which works on 6.1 in our tests. The 1.3 limit should be lifted and 1.3.0 tested.

Suggested limits: `Django>=5.2,<6.2`, `wagtail>=7.0,<9`, `django-newsletter>=1.2,<1.4`. Test them before release.

## 2. Admin "Subscribers" list crashes: HTTP 500 (blocker)

`prblm_mailer/models.py:293`, in `groups_label()`:
```python
return format_html('<span style="color:#9aa0a6">—</span>')
```
Django 6.0 removed calling `format_html()` without arguments:
```
TypeError: args or kwargs must be provided.
```
This breaks `/admin/snippets/prblm_mailer/subscriber/` and `.../results/` whenever a subscriber has no groups. Both returned 200 on Django 5.0.

**Fix:**
```python
from django.utils.safestring import mark_safe
return mark_safe('<span style="color:#9aa0a6">—</span>')
```
This was the only no-argument `format_html` call found in prblm-mailer, django-newsletter, anymail, wagtailcaptcha, django-recaptcha, sorl-thumbnail, widget-tweaks, browser-reload and rollbar.

## 3. Local and console delivery modes crash once a site uses `MAILERS` (blocker for local dev)

`prblm_mailer/sending.py:137` and `:141-143`, in `_local_connection()`:
```python
get_connection("django.core.mail.backends.console.EmailBackend")
get_connection("django.core.mail.backends.smtp.EmailBackend", host=host, port=port)
```
Django 6.1 deprecates the `EMAIL_*` settings in favour of `MAILERS`. Once a site defines `MAILERS`, as breakingbeats now does, `get_connection()` with a backend path raises:
```
RuntimeError: get_connection(backend, ...) is not supported with MAILERS.
```
Verified on breakingbeats. `DELIVERY="local"` and `DELIVERY="console"` both fail, which breaks newsletters, test sends and opt-in emails in local development.

The `mailgun` mode is **not** affected. `_send_mailgun()` calls `get_connection()` with no arguments, which returns the default mailer, so staging and production keep working.

**Fix:** on Django 6.1+ (when `hasattr(django.core.mail, "mailers")`), build the local connection without `get_connection(path)`. For example, instantiate the backend class directly:
```python
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
ConsoleBackend()                       # console
SMTPBackend(host=host, port=port)      # local inbox
```
Alternatively, add a setting naming a `MAILERS` alias and use `django.core.mail.mailers[alias]`. Keep the old path for Django < 6.1.

`get_connection()` with no arguments (`sending.py:184`) still works, but it is deprecated and will be removed in "Django 2028". Move it to `mailers.default`, or to `using=` on send.

## 4. Newsletter images can arrive as WebP or AVIF (Outlook can't show them)

Wagtail 8.0: "AVIF and WebP images are no longer converted to PNG by default". If no `format-*` filter is given, a WebP upload now gives a WebP rendition. The email block templates have no format filter:

| Template | Tag |
|---|---|
| `templates/prblm_mailer/blocks/email_image.html:1` | `{% image value.image width-1400 as img %}` |
| `templates/prblm_mailer/blocks/email_header.html:1` | `{% image value.image width-600 as img %}` |
| `templates/prblm_mailer/blocks/email_two_column.html:1` | `{% image value.image width-1000 as img %}` |
| `templates/prblm_mailer/blocks/email_footer.html:1` | `{% image value.image width-320 as img %}` |

Confirmed on breakingbeats: the 3 WebP images in its library now render as `.webp` where they used to render as `.png`. Outlook desktop and some other mail clients can't display WebP.

**Fix:** add an explicit format to each tag: `format-jpeg` for photos, or `format-png` for logos and transparency. For example:
`{% image value.image width-1400 format-jpeg as img %}`

## 5. Deprecations (not breaking yet)

- **`get_connection()`** (`sending.py:184`): deprecated in Django 6.1. See section 3.
- **`connection=`** on messages (`sending.py:163, 207, 253, 345`): it works with the default mailer, but the new API is `using=`.

## Checked and fine on Wagtail 8.1

These are all still present in Wagtail 8.1 with compatible signatures:
- `ActionMenuItem`
- the `register_snippet_action_menu_item` hook
- `HeaderButton`
- `IndexView.get_header_buttons`
- the `insert_global_admin_css` and `insert_global_admin_js` hooks
- `require_admin_access`
- `PreviewableMixin.serve_preview`
- `StructBlock.get_context`
- `AbstractFormField.panels`
- `process_form_submission`
- the `slim_header.html` include

Other admin screens:
- **Broadcasts admin, subscriber import, newsletter opt-in pages:** these return the same status codes as on the old stack.
- **Wagtail 7.3.1 message escaping:** our `messages.*` calls are plain text, so this doesn't affect us.

## How this was found

The tools live outside the repo, in `~/Documents/breakingbeats-baseline/tools/`:
- `snapshot.sh` crawls every public page and about 1,500 admin screens, renders 9 versions of each image, round-trips all rich text and validates every page. Writes happen in a transaction that is rolled back, on throwaway copies of the data.
- `compare.py` compares two snapshots.

The old stack (`staging-mailgun-newsletter`: Django 5.0.4, Wagtail 6.0.2) and the new stack were run on the same data. Everything matched except issues 2 and 4 above, plus the expected Wagtail 8 changes.
