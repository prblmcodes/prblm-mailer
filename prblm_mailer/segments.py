"""Turn a form submission's answers into subscriber groups.

A form field ticked "use for grouping" on the host site contributes its answer
to the subscriber as a `SubscriberTag` — a *(group, value)* pair. This happens at
**submission** time, not at send time: once the answer is stored on the subscriber,
renaming or deleting that form field later can't change or lose anyone's group.

The page is duck-typed (anything with `form_fields` whose rows carry
`use_for_grouping`), so this module never imports `core` — that would be a circular
import, since the host site already reaches into this package to subscribe people.
"""
import logging

from django.core import signing
from django.utils.text import slugify

logger = logging.getLogger(__name__)

# A group name/value longer than this is almost certainly not a real category.
MAX_LABEL = 160

# Only fields with a fixed, predefined set of answers may be grouping fields. A
# free-text field (or email/number/date) would mint a new one-person group on every
# submission — thousands of useless groups. Choice fields keep groups finite.
CHOICE_FIELD_TYPES = {"dropdown", "radio", "checkboxes", "multiselect"}

# The opt-in field is a single checkbox: it is the one field type with an
# unambiguous "no" (left unticked), which is what consent has to hinge on.
OPTIN_FIELD_TYPE = "checkbox"

# Namespace for the signup block's group token (see sign_group).
GROUP_SALT = "prblm_mailer.segments.group"


def sign_group(group_name, value_label):
    """A tamper-proof token carrying one (group, answer) pair.

    The newsletter signup block posts to a shared view that can't tell which block
    submitted, so the group has to ride along with the request. Signing it means a
    visitor can't edit the page's HTML to put themselves in a group they were
    never offered.
    """
    return signing.dumps([group_name, value_label], salt=GROUP_SALT)


def unsign_group(token):
    """`[(group, answer)]` from a token, or `[]` if it's missing or tampered with."""
    if not token:
        return []
    try:
        group_name, value_label = signing.loads(token, salt=GROUP_SALT)
    except (signing.BadSignature, ValueError, TypeError):
        logger.warning("Ignored a bad newsletter group token")
        return []
    group_name = str(group_name).strip()[:80]
    value_label = str(value_label).strip()[:MAX_LABEL]
    return [(group_name, value_label)] if (group_name and value_label) else []


def grouping_specs(page):
    """`[(form field name, group name), …]` for the page's grouping fields.

    The form field name is Wagtail's `clean_name` — the key the answer arrives
    under in `cleaned_data`.
    """
    if page is None:
        return []
    try:
        fields = page.form_fields.all()
    except AttributeError:
        return []
    return [
        (f.clean_name, f.resolved_group_name)
        for f in fields
        if getattr(f, "use_for_grouping", False)
        # Defensive: skip non-choice fields even if the flag was set some other way,
        # so a text field can never explode the group list.
        and getattr(f, "field_type", "") in CHOICE_FIELD_TYPES
    ]


def optin_field_name(page):
    """The `clean_name` of the page's newsletter opt-in checkbox, or None.

    Duck-typed like `grouping_specs`, for the same reason: the page belongs to the
    host site. First marked field wins — two consent fields is a mistake, and
    guessing between them would be worse than being predictable.
    """
    if page is None:
        return None
    try:
        fields = page.form_fields.all()
    except AttributeError:
        return None
    for f in fields:
        if getattr(f, "use_for_optin", False) and getattr(f, "field_type", "") == OPTIN_FIELD_TYPE:
            return f.clean_name
    return None


def _values(raw):
    """The answer(s) in a submitted value.

    Checkboxes and multi-selects submit a list — each choice becomes its own tag,
    so one field can put somebody in several groups at once.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw).strip()
    return [text] if text else []


def tags_from_submission(page, cleaned_data):
    """`[(group name, answer), …]` for this submission.

    Blank answers contribute nothing at all — see `apply_tags` for why that
    matters.
    """
    tags = []
    for field_name, group_name in grouping_specs(page):
        for value in _values(cleaned_data.get(field_name)):
            if len(value) > MAX_LABEL or not slugify(value):
                # Unsluggable or absurdly long — not a real category.
                continue
            tags.append((group_name[:80], value[:MAX_LABEL]))
    return tags


def apply_tags(subscription, tags):
    """Store `tags` on the subscription, replacing that group's previous answer.

    Replacement is **scoped to the groups in this submission**: answering a page
    that only asks about Interest must not wipe a Topic group set elsewhere.

    A group missing from `tags` is therefore left untouched — which is also why
    `tags_from_submission` drops blanks. An optional field left empty means "no
    answer", not "remove me from that group"; clearing on blank would silently
    drop people out of groups whenever they skipped a question.
    """
    from .models import SubscriberTag

    if not tags:
        return

    groups = {group for group, _ in tags}
    subscription.tags.remove(*subscription.tags.filter(group_name__in=groups))

    for group_name, value_label in tags:
        tag, _ = SubscriberTag.objects.get_or_create(
            group_name=group_name,
            value_slug=slugify(value_label)[:80],
            defaults={"value_label": value_label},
        )
        subscription.tags.add(tag)

    logger.info(
        "Tagged %s: %s", subscription.email_field,
        ", ".join(f"{g} → {v}" for g, v in tags),
    )
