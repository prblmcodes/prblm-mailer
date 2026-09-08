"""Who a broadcast actually goes to.

The **one** place recipients are chosen. Everything that needs to know — the send
page's "this will go to N subscribers" count, and the send itself — calls
`resolve()`, so the number shown and the number mailed can never drift apart.

It is also the seam for future ways of picking an audience (e.g. "everyone who
didn't click last time"): they become another branch here rather than a rewrite of
the send pipeline.
"""
from django.db.models import Q

from .subscriptions import confirmed_subscriptions


def resolve(broadcast):
    """The subscriptions this broadcast will be sent to.

    Groups can only ever *narrow* the audience: `confirmed_subscriptions()` stays
    the base, so someone unconfirmed or unsubscribed is unreachable no matter what
    groups they hold.

    Selecting nothing means everyone — the default, and what every existing
    broadcast does.

    Several groups are combined with OR: anyone in *any* of them. "Ungrouped" is
    not a group but the absence of all of them, which is why it's a separate flag
    rather than a tag — nothing has to be maintained when someone later gains a
    real group.
    """
    from .models import SubscriberTag

    base = confirmed_subscriptions()

    tags = list(broadcast.send_to_tags.all()) if broadcast.pk else []
    ungrouped = broadcast.include_ungrouped

    if not tags and not ungrouped:
        return base

    # Everything ticked means "the whole list", so say so rather than listing every
    # group back at the user.
    #
    # Caveat: this is judged against the groups that exist *right now*. If a new
    # group is created after this was saved, the selection no longer covers
    # everything and its members drop out. A proper fix would store an explicit
    # "everyone" mode on the broadcast; deliberately not done, because the only way
    # to reach the bad case is deleting a tag from a shell (tags aren't in the admin).
    if ungrouped:
        all_tag_ids = set(SubscriberTag.objects.values_list("pk", flat=True))
        if {t.pk for t in tags} >= all_tag_ids:
            return base

    query = Q(tags__in=tags) if tags else Q()
    if ungrouped:
        query |= Q(tags__isnull=True)
    # distinct(): a subscriber in two selected groups joins twice.
    return base.filter(query).distinct()


def describe(broadcast):
    """A short plain-English label for who this goes to, for the send page."""
    from .models import SubscriberTag

    tags = list(broadcast.send_to_tags.all()) if broadcast.pk else []
    if not tags and not broadcast.include_ungrouped:
        return "everyone"
    if broadcast.include_ungrouped:
        all_tag_ids = set(SubscriberTag.objects.values_list("pk", flat=True))
        if {t.pk for t in tags} >= all_tag_ids:
            return "everyone"

    parts = [f"{t.group_name}: {t.value_label}" for t in tags]
    if broadcast.include_ungrouped:
        parts.append("no group")
    return ", ".join(parts)
