"""Wagtail admin wiring: Newsletters + Subscribers snippets, the Send page, the
Save & send button, and the block-editor CSS/JS."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.action_menu import ActionMenuItem
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import CreateView, EditView, SnippetViewSet

from . import admin_views
from .models import Broadcast, Subscriber

# The "Save & send" submit button: saves like a normal save, then redirects to send.
SEND_ACTION = "action-send-newsletter"


class _SaveAndSendMixin:
    def get_success_url(self):
        if SEND_ACTION in self.request.POST and getattr(self, "object", None):
            return reverse("prblm_mailer_send", args=[self.object.pk])
        return super().get_success_url()


class BroadcastCreateView(_SaveAndSendMixin, CreateView):
    pass


class BroadcastEditView(_SaveAndSendMixin, EditView):
    def dispatch(self, request, *args, **kwargs):
        # A sent newsletter is locked (a permanent record of what went out). Send
        # the editor to the read-only Send page instead, on GET and POST.
        obj = Broadcast.objects.filter(pk=kwargs.get("pk")).first()
        if obj is not None and obj.is_sent:
            messages.info(
                request,
                "This newsletter has already been sent, so it's read-only. "
                "Use Duplicate to make an editable copy.",
            )
            return redirect("prblm_mailer_send", pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)


class BroadcastViewSet(SnippetViewSet):
    model = Broadcast
    icon = "mail"
    menu_label = "Newsletters"
    menu_name = "newsletters"
    add_to_admin_menu = True
    menu_order = 250
    add_view_class = BroadcastCreateView
    edit_view_class = BroadcastEditView
    list_display = ["subject", "status", "created_at", "sent_at", "clicks_column", "opens_column"]
    list_filter = ["status"]
    search_fields = ["subject"]

    def get_queryset(self, request):
        # Count clicks/opens per row in one query, not one per row (the column
        # methods read these annotations when present).
        from django.db.models import Count, Q
        from .models import EngagementEvent

        queryset = super().get_queryset(request)
        if queryset is None:
            queryset = self.model._default_manager.all()
        return queryset.annotate(
            click_total=Count("engagement", distinct=True,
                               filter=Q(engagement__kind=EngagementEvent.KIND_CLICK)),
            open_total=Count("engagement", distinct=True,
                             filter=Q(engagement__kind=EngagementEvent.KIND_OPEN)),
        )


register_snippet(BroadcastViewSet)


class SubscriberEditView(EditView):
    """Subscribers aren't hand-edited — editing would corrupt the opt-in/confirm
    state — so any edit request redirects to the read-only inspect view."""

    def dispatch(self, request, *args, **kwargs):
        return redirect("wagtailsnippets_prblm_mailer_subscriber:inspect", pk=kwargs.get("pk"))


class SubscriberViewSet(SnippetViewSet):
    """The list: read it, prune it, but don't hand-edit it. People join via the
    signup form (double opt-in) and leave via unsubscribe or a hard bounce."""

    model = Subscriber
    icon = "group"
    menu_label = "Subscribers"
    menu_name = "subscribers"
    add_to_admin_menu = True
    menu_order = 260
    inspect_view_enabled = True
    copy_view_enabled = False
    edit_view_class = SubscriberEditView
    inspect_view_fields = [
        "email_field", "name_field", "status_label", "groups_label",
        "subscribe_date", "unsubscribe_date", "create_date",
    ]
    list_display = ["email_field", "name_field", "status_label", "groups_label", "subscribe_date"]
    list_filter = ["subscribed", "unsubscribed", "newsletter", "tags"]
    search_fields = ["email_field", "name_field"]

    def get_queryset(self, request):
        # One query for everyone's groups + the newsletter, not one per row.
        queryset = super().get_queryset(request)
        if queryset is None:
            queryset = self.model._default_manager.all()
        return queryset.select_related("newsletter").prefetch_related("tags")

    def get_common_view_kwargs(self, **kwargs):
        # No "Add subscriber" button — people join only via double opt-in.
        kwargs = super().get_common_view_kwargs(**kwargs)
        kwargs["add_url_name"] = None
        return kwargs


register_snippet(SubscriberViewSet)


@hooks.register("register_admin_urls")
def register_send_url():
    return [
        path("newsletters/<int:pk>/send/", admin_views.send_newsletter, name="prblm_mailer_send"),
        path("newsletters/<int:pk>/send/confirm/", admin_views.confirm_send, name="prblm_mailer_confirm"),
        path("newsletters/<int:pk>/duplicate/", admin_views.duplicate_newsletter, name="prblm_mailer_duplicate"),
    ]


class SaveAndSendMenuItem(ActionMenuItem):
    """A 'Save & send' button in the editor: saves, then the views redirect to send."""

    name = SEND_ACTION
    label = "Save & send"
    icon_name = "mail"
    order = 90

    def is_shown(self, context):
        return True


@hooks.register("register_snippet_action_menu_item")
def add_send_action(model):
    if model is Broadcast:
        return SaveAndSendMenuItem()


@hooks.register("insert_global_admin_css")
def email_block_field_layout():
    """Lay the block fields into rows (6-col grid), and make select/chooser fields
    fill their cell. Self-contained so the package needs no host CSS."""
    from django.utils.safestring import mark_safe

    glist = ".hdr-fields,.ftr-fields,.content-fields,.twocol-fields,.img-fields,.spacer-fields".split(",")
    cells = ",".join(f"{g}>[data-contentpath]" for g in glist)
    css = (
        f"{','.join(glist)}{{display:grid;grid-template-columns:repeat(6,1fr);gap:0 1rem}}"
        f"{cells}{{grid-column:span 3;min-width:0}}"
        ".content-fields>[data-contentpath='heading'],"
        ".content-fields>[data-contentpath='description'],"
        ".twocol-fields>[data-contentpath='description']{grid-column:1/-1}"
        # Make select + chooser fields fill their grid cell (Wagtail shrinks them).
        ".w-field--select{display:block}"
        ".w-field--select select{width:100%;box-sizing:border-box}"
        ".w-field[class*=chooser]{display:block}"
        ".w-field[class*=chooser] .w-field__input{width:100%;max-width:none}"
    )
    return mark_safe(f"<style>{css}</style>")


@hooks.register("insert_global_admin_js")
def color_picker_js():
    """Swatch enhancer for the blocks' colour fields."""
    from django.templatetags.static import static
    from django.utils.safestring import mark_safe

    return mark_safe(f'<script src="{static("prblm_mailer/js/color_picker.js")}"></script>')
