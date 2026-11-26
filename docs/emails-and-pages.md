# Confirmation email and public pages

These are what your subscribers see outside the newsletters themselves: the email asking them
to confirm, and the pages they land on from it. They all come styled with your `FROM_NAME` and
`BRAND_COLOR`, and each one is a template you can override.

- [The confirmation email](#the-confirmation-email)
- [The public pages](#the-public-pages)
- [Restyling the pages](#restyling-the-pages)

---

## The confirmation email

New subscribers get a short email with a **Confirm** button: a centred card in your brand
colour, a fallback link they can paste, and preview text for the inbox list. It is sent through
[`DELIVERY`](delivery-and-mailgun.md), like everything else.

### Where its link points

The link is built by django-newsletter, which takes the domain from Django's **Site** record
(not from `WAGTAILADMIN_BASE_URL`) and the scheme from `NEWSLETTER_USE_HTTPS`.

- **Domain:** Django creates the Site record as `example.com`. While it still has that
  placeholder, the plugin copies your host from `WAGTAILADMIN_BASE_URL` into it on the next
  signup, and `manage.py check` warns (`W002`) until then. A domain you set yourself is never
  changed. To set it by hand:

  ```python
  from django.contrib.sites.models import Site
  Site.objects.filter(id=1).update(domain="your-site.com")   # "localhost:8000" locally
  ```

- **http or https:** `NEWSLETTER_USE_HTTPS` defaults to `True`, which breaks links on a local
  http server. Use:

  ```python
  NEWSLETTER_USE_HTTPS = not DEBUG
  ```

  `manage.py check` warns (`W003`) when it's on for an http site.

### Changing it

Copy the plugin's template into your project as `templates/newsletter/message/subscribe.html`
and edit it. Find the original with:

```bash
python -c "import prblm_mailer, pathlib; print(pathlib.Path(prblm_mailer.__file__).parent / 'templates/prblm_mailer/optin/subscribe.html')"
```

As soon as your project has that file, the plugin uses yours. Keep the confirmation link:

```django
<a href="{{ site_url }}{{ subscription.subscribe_activate_url }}">Confirm</a>
```

Available in the template: `newsletter`, `subscription`, `site`, `site_url`, `brand_color` and
`from_name`. The subject line and plain-text version are django-newsletter's
(`newsletter/message/subscribe_subject.txt` and `subscribe.txt`); override those the same way.

## The public pages

| Address | When people see it |
|---|---|
| `/newsletter/<slug>/subscribe/` | A simple signup page, if you link to it |
| `/newsletter/<slug>/subscribe/email-sent/` | After signing up: "check your inbox" |
| `/newsletter/<slug>/subscription/<email>/subscribe/activate/<code>/` | The link in the confirmation email |
| `/newsletter/<slug>/subscribe/activation-completed/` | After confirming |
| `/newsletter/<slug>/unsubscribe/` | The unsubscribe form |
| `/newsletter/<slug>/unsubscribe/activation-completed/` | After unsubscribing |
| `/mailer/deny/` | After declining a signup from the confirm page |
| `/mailer/unsubscribe/<token>/` | The one-click unsubscribe link from mail apps |

django-newsletter's own versions of these are unstyled. The plugin replaces the shared layout
they all use (`newsletter/common.html`) and rewrites the confirm, "check your inbox" and
"done" pages; the signup and unsubscribe forms keep django-newsletter's markup inside the
plugin's layout. The styling
is inline and self-contained, because people arrive mid-flow from an email client, and no web
fonts are loaded on the visitor's behalf.

Behaviour worth knowing:

- **A reused link says so.** Opening a confirmation link again shows *"Already confirmed —
  nothing more to do"* instead of a form that looks like it failed. The same goes for an
  already-used unsubscribe link.
- **Deny subscription.** If someone was signed up by mistake (a typo, or a stranger using their
  address), the confirm page has a decline button. It deletes the pending signup and disables
  the link. It can never remove someone who already confirmed.
- **Expired or invalid one-click links** show one neutral page that doesn't reveal which of the
  two it was.

## Restyling the pages

Pick the level you need.

**Use your site's own layout.** Create `templates/newsletter/common.html` in your project; it
takes priority over the plugin's. Hand the page content to your own base template:

```django
{% extends "base.html" %}
{% block content %}{% block body %}{% endblock %}{% endblock %}
```

**Keep the layout, change the look.** Copy the plugin's version of that file and edit its CSS.
(A template can't extend another of the same name, so copy rather than extend.)

```bash
python -c "import prblm_mailer, pathlib; print(pathlib.Path(prblm_mailer.__file__).parent / 'templates/newsletter/common.html')"
# copy that file to templates/newsletter/common.html in your project
```

**Change one page only.** Override just that template, for example
`templates/newsletter/subscription_subscribe_activated.html`. The full set of page templates is
in django-newsletter's `newsletter/templates/newsletter/` folder.

Your templates can read plugin settings with
`{% load prblm_mailer_tags %}{% mailer_setting "BRAND_COLOR" %}` (or `"FROM_NAME"`).

These overrides depend on `prblm_mailer` coming **before** `newsletter` in `INSTALLED_APPS`.
`with_required_apps` arranges that; keep it so if you list the apps yourself.
