# Signup forms and groups

The plugin doesn't ship a signup form and never picks up forms on its own — a form only adds
people to your list when **you** connect it. You keep your own form; one line (or one mixin)
hands its data to the plugin, which creates a **pending** subscriber and sends the
confirmation email. They receive newsletters only after clicking the confirmation link.

- [The one function](#the-one-function)
- [A plain Django form](#a-plain-django-form)
- [A Wagtail form page — with the plugin's base classes](#a-wagtail-form-page--with-the-plugins-base-classes)
- [An opt-in checkbox on a contact form](#an-opt-in-checkbox-on-a-contact-form)
- [A Wagtail form page — by hand](#a-wagtail-form-page--by-hand)
- [Groups](#groups)
- [Gotchas](#gotchas)

---

## The one function

Everything below ends up calling:

```python
from prblm_mailer.subscriptions import subscribe_from_form

subscribe_from_form(cleaned_data, page=None, groups=None)
```

- It finds the email address (and a name, if there is one) in `cleaned_data` itself.
- It creates a pending subscriber and sends the confirmation email (through
  [`DELIVERY`](delivery-and-mailgun.md)).
- It **never raises**, so a newsletter problem can't break your visitor's form submission. It
  returns the subscription, or `None` if there was nothing to do (no email address, for
  example). Problems are logged.
- Someone **already confirmed** is left exactly as they are: no second confirmation email, and
  their groups aren't changed by re-submitting.
- Someone who **unsubscribed earlier** and signs up again gets a fresh confirmation email; they
  are back on the list only once they click it.

A signup form **must include an email field**.

## A plain Django form

```python
# forms.py
from django import forms

class NewsletterSignupForm(forms.Form):
    email = forms.EmailField(label="Your email")
    name = forms.CharField(label="Your name", required=False)
```

```python
# views.py
from django.contrib import messages
from django.shortcuts import redirect, render

from prblm_mailer.subscriptions import subscribe_from_form
from .forms import NewsletterSignupForm

def newsletter_signup(request):
    if request.method == "POST":
        form = NewsletterSignupForm(request.POST)
        if form.is_valid():
            subscribe_from_form(form.cleaned_data)          # ← the only plugin line
            messages.success(request, "Almost there — check your inbox to confirm.")
            return redirect("newsletter_signup")
    else:
        form = NewsletterSignupForm()
    return render(request, "signup.html", {"form": form})
```

Tell people to **check their email** — they aren't subscribed until they click the link.

To put them in a group, pass `(group, answer)` pairs:

```python
groups = [("Interest", form.cleaned_data["interest"])]
subscribe_from_form(form.cleaned_data, groups=groups)   # tags them "Interest: guitar"
```

## A Wagtail form page — with the plugin's base classes

This is the recommended way. Swap two base classes and the editor gets a *Collect newsletter
subscribers* switch on the page plus grouping and opt-in options on each field — no other code.

```python
from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.contrib.forms.models import AbstractEmailForm
from wagtail.fields import RichTextField

from prblm_mailer.form_pages import AbstractGroupingFormField, NewsletterFormMixin


class FormField(AbstractGroupingFormField):                     # ← was AbstractFormField
    page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)


class FormPage(NewsletterFormMixin, AbstractEmailForm):         # ← the mixin comes FIRST
    intro = models.TextField(blank=True)
    thank_you_text = RichTextField(blank=True)

    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("intro"),
        InlinePanel("form_fields", label="Form fields"),
        FieldPanel("thank_you_text"),
        *NewsletterFormMixin.newsletter_panels,     # ← the "Collect newsletter subscribers" switch
    ]
```

Then run `python manage.py makemigrations` and `migrate`. In the page editor, turn on
**Collect newsletter subscribers**, and every submission starts the double opt-in.

The base classes work with `AbstractForm` as well as `AbstractEmailForm`.

## An opt-in checkbox on a contact form

A contact form can offer the newsletter instead of signing everyone up. Add a **checkbox**
field — "Keep me posted", say — and tick **Use as the newsletter opt-in** on it. From then on
the page subscribes only the people who tick the box. Everyone else's submission is still saved
and still emails you as normal; they just aren't added to the list, and get no confirmation
email.

- **Ticked = subscribe.** For an opt-*out* style form (box ticked by default), set the field's
  default value to checked.
- It has to be a **checkbox** — the one field type with an unambiguous "no". Other types are
  rejected in the editor.
- If the opt-in field is missing from a submission, that counts as **no** — silence isn't
  consent.
- Only the first field marked as the opt-in is used.
- A page with no opt-in field subscribes every submission (when *Collect newsletter
  subscribers* is on).

## A Wagtail form page — by hand

If you can't change your base classes, do what the mixin does yourself: a switch on the page,
the `process_form_submission` hook, and — for grouping — two attributes on the field.

```python
from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField

from prblm_mailer.subscriptions import subscribe_from_form


class FormField(AbstractFormField):
    page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)

    use_for_grouping = models.BooleanField(default=False)       # grouping (optional)
    group_name = models.CharField(max_length=80, blank=True)

    panels = AbstractFormField.panels + [
        FieldPanel("use_for_grouping"),
        FieldPanel("group_name"),
    ]

    @property
    def resolved_group_name(self):
        return self.group_name or self.label


class FormPage(AbstractEmailForm):
    collect_newsletter_subscribers = models.BooleanField(default=False)

    content_panels = AbstractEmailForm.content_panels + [
        InlinePanel("form_fields", label="Form fields"),
        FieldPanel("collect_newsletter_subscribers"),
    ]

    def process_form_submission(self, form):
        submission = super().process_form_submission(form)      # saves AND returns it
        if self.collect_newsletter_subscribers:
            subscribe_from_form(form.cleaned_data, page=self)
        return submission
```

The plugin recognises `use_for_grouping` and `resolved_group_name` on any field model, so
grouping works exactly as with the base classes. A `use_for_optin` boolean on a checkbox field
is recognised the same way.

---

## Groups

A **group** tags a subscriber with an answer they gave when signing up — a *"Which instrument?"*
dropdown answered *Guitar* becomes **Instrument: Guitar**. When sending, you can pick groups so
a newsletter only goes to the people in them ([choosing who gets it](writing-newsletters.md#choosing-who-gets-it)).

Groups are optional. Without any, every newsletter goes to the whole list.

**On a Wagtail form page** (with the base classes or by hand), tick **Use for grouping** on a
field in the page editor. The group is named after the field's label, or after *Group name* if
you fill that in. Every submission then tags the subscriber automatically.

**Only choice fields can group people** — dropdown, radio buttons, checkboxes and multi-select.
A free-text field would create a new one-person group for every submission, so the editor
rejects it.

**Answers are stored on the subscriber** at signup. Renaming or deleting the form field later
never takes anyone out of their group. Groups also come in through a
[CSV import](subscribers.md#importing-a-csv).

## Gotchas

- **The mixin must come first:** `class FormPage(NewsletterFormMixin, AbstractEmailForm)`.
  Otherwise its `process_form_submission` never runs.
- **Return the submission from `super()`** in your own `process_form_submission`. Don't also
  create one yourself, or every submission is saved twice.
- **Use `.get()`** for optional fields in your own code (`form_data.get("first_name", "")`); a
  field that wasn't submitted raises `KeyError` with `form_data["first_name"]`.
- **Under `dry_run`, the confirmation email is only logged.** Use `console`, `local` or
  `mailgun` to actually receive it.
- **Changing your field model** (switching to `AbstractGroupingFormField`, or upgrading the
  plugin across a version that adds a field to it) needs `makemigrations` in **your** app.
