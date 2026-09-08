from django.urls import path

from . import views

app_name = "prblm_mailer"

urlpatterns = [
    # RFC 8058 one-click unsubscribe target for the List-Unsubscribe header.
    path("unsubscribe/<str:token>/", views.oneclick_unsubscribe, name="oneclick_unsubscribe"),
    # "Deny subscription" on the confirm page: declines a pending signup.
    path("deny/", views.deny_subscription, name="deny_subscription"),
]
