"""Cross-version guarantees: Django 6.1 mailers, Wagtail 8 image formats, Django 6 HTML.

Each test here pins a break found upgrading a host to Wagtail 8.1 + Django 6.1, and
runs on every supported version — the old code paths must keep working too.
"""
import ast
import io
import pathlib
import warnings
from unittest import mock

from django.core import mail
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.test import TestCase, override_settings

from newsletter.models import Subscription

from prblm_mailer import sending
from prblm_mailer.models import Subscriber
from prblm_mailer.templatetags.prblm_mailer_tags import email_image

from .test_sending import a_broadcast, a_newsletter

PACKAGE = pathlib.Path(sending.__file__).parent
HAS_MAILERS = sending.mailers is not None
# What Django 6.1 reports for a deprecated mail API used from outside Django.
try:
    from django.utils.deprecation import RemovedInDjango2028Warning
except ImportError:  # Django < 6.1: nothing of ours can trip it
    RemovedInDjango2028Warning = None

# A site that has moved to Django 6.1's MAILERS.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}


def _settings(**kw):
    return {"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", **kw}


class LocalConnectionTests(TestCase):
    def test_console_is_the_console_backend(self):
        self.assertIsInstance(sending._local_connection("console"), ConsoleBackend)

    @override_settings(PRBLM_MAILER=_settings(LOCAL_SMTP_HOST="127.0.0.1", LOCAL_SMTP_PORT=1025),
                       EMAIL_HOST_USER="real-user", EMAIL_HOST_PASSWORD="real-pass",
                       EMAIL_USE_TLS=True)
    def test_local_inbox_never_borrows_the_real_smtp_login(self):
        with mock.patch.object(sending, "_check_smtp_reachable"):
            backend = sending._local_connection("local")
        self.assertIsInstance(backend, SMTPBackend)
        self.assertEqual((backend.host, backend.port), ("127.0.0.1", 1025))
        self.assertFalse(backend.username)
        self.assertFalse(backend.use_tls)


class MailersTests(TestCase):
    """DELIVERY='console'/'local' crashed once a host defined MAILERS (Django 6.1)."""

    def setUp(self):
        if not HAS_MAILERS:
            self.skipTest("MAILERS arrived in Django 6.1")

    @override_settings(MAILERS=MAILERS, PRBLM_MAILER=_settings(DELIVERY="console"))
    def test_console_test_send_works_with_mailers(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            sending.send_test(a_broadcast(subject="Console"), "me@x.co")
        self.assertIn("[TEST] Console", out.getvalue())

    @override_settings(MAILERS=MAILERS, PRBLM_MAILER=_settings(DELIVERY="console"))
    def test_console_optin_works_with_mailers(self):
        sub = Subscription.objects.create(newsletter=a_newsletter(), email_field="new@x.co")
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            sending.send_optin(sub, "subscribe")
        self.assertIn("new@x.co", out.getvalue())

    @override_settings(MAILERS=MAILERS, PRBLM_MAILER=_settings(DELIVERY="mailgun"))
    def test_broadcast_goes_through_the_default_mailer(self):
        Subscription.objects.create(newsletter=a_newsletter(), email_field="a@x.co",
                                    subscribed=True)
        mail.outbox = []
        sending.send_broadcast(a_broadcast().pk)
        self.assertEqual([m.to for m in mail.outbox], [["a@x.co"]])


class DeprecationTests(TestCase):
    """Nothing we call is on Django 6.1's removal list (get_connection, connection=…)."""

    def setUp(self):
        if RemovedInDjango2028Warning is None:
            self.skipTest("The mail deprecations arrived in Django 6.1")

    def ours(self, caught):
        return [str(w.message) for w in caught
                if issubclass(w.category, RemovedInDjango2028Warning)
                and str(PACKAGE) in w.filename]

    @override_settings(MAILERS=MAILERS)
    def test_every_delivery_path_is_warning_free(self):
        Subscription.objects.create(newsletter=a_newsletter(), email_field="a@x.co",
                                    subscribed=True)
        sub = Subscription.objects.create(newsletter=a_newsletter(), email_field="b@x.co")
        with warnings.catch_warnings(record=True) as caught, mock.patch("sys.stdout"):
            warnings.simplefilter("always")
            for mode in ("console", "mailgun"):
                with override_settings(PRBLM_MAILER=_settings(DELIVERY=mode)):
                    sending.send_test(a_broadcast(), "me@x.co")
                    sending.send_optin(sub, "subscribe")
                    sending.send_broadcast(a_broadcast().pk)
        self.assertEqual(self.ours(caught), [])


class GroupsLabelTests(TestCase):
    def test_no_groups_renders_a_dash(self):
        """Django 6 raises on format_html() with nothing to format — the listing 500'd."""
        sub = Subscription.objects.create(newsletter=a_newsletter(), email_field="a@x.co")
        self.assertIn("—", Subscriber.objects.get(pk=sub.pk).groups_label())

    def test_no_bare_format_html_anywhere(self):
        """Catch the same mistake anywhere in the package, on every Django version."""
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "format_html"
                        and len(node.args) <= 1 and not node.keywords):
                    offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
        self.assertEqual(offenders, [])


class EmailImageTests(TestCase):
    """Wagtail 8 stopped converting WebP/AVIF to PNG; Outlook can't show WebP."""

    def setUp(self):
        # SQLite reuses an image pk after each test's rollback, and Wagtail caches
        # renditions by pk — the last test's JPEG would answer for this test's PNG.
        from django.core.cache import cache
        cache.clear()

    def an_image(self, fmt, ext, mode="RGB"):
        from django.core.files.images import ImageFile
        from PIL import Image
        from wagtail.images import get_image_model

        buf = io.BytesIO()
        Image.new(mode, (800, 600), "red").save(buf, fmt)
        buf.seek(0)
        return get_image_model().objects.create(
            title=ext, file=ImageFile(buf, name=f"photo.{ext}"))

    def extension(self, image):
        return pathlib.Path(email_image(image, "width-400").file.name).suffix

    def test_webp_becomes_png(self):
        self.assertEqual(self.extension(self.an_image("WEBP", "webp")), ".png")

    def test_jpeg_stays_jpeg(self):
        self.assertEqual(self.extension(self.an_image("JPEG", "jpg")), ".jpg")

    def test_png_stays_png(self):
        self.assertEqual(self.extension(self.an_image("PNG", "png", "RGBA")), ".png")

    def test_the_resize_still_applies(self):
        self.assertEqual(email_image(self.an_image("WEBP", "webp"), "width-400").width, 400)

    def test_block_templates_use_it(self):
        """No email block may go back to a bare {% image %}: it would ship WebP again."""
        blocks = PACKAGE / "templates" / "prblm_mailer" / "blocks"
        bare = [p.name for p in blocks.glob("*.html") if "{% image " in p.read_text()]
        self.assertEqual(bare, [])


class SubscriberAddUrlTests(TestCase):
    """The Add button is hidden, but Wagtail still registers add/ — opened directly it
    500'd (CreateView with no add_url_name). It must land somewhere deliberate instead."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_superuser("admin", "a@b.co", "pw")
        self.client.force_login(user)

    def url(self, name):
        from django.urls import reverse

        return reverse(f"wagtailsnippets_prblm_mailer_subscriber:{name}")

    def test_add_url_redirects_to_the_list(self):
        response = self.client.get(self.url("add"))
        self.assertRedirects(response, self.url("list"), fetch_redirect_response=False)

    def test_posting_to_it_creates_nobody(self):
        response = self.client.post(self.url("add"), {"email_field": "sneaky@x.co"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Subscription.objects.filter(email_field="sneaky@x.co").exists())

    def test_the_list_explains_how_people_join(self):
        response = self.client.get(self.url("add"), follow=True)
        text = " ".join(str(m) for m in response.context["messages"])
        self.assertIn("CSV import", text)

    def test_still_no_add_button(self):
        html = self.client.get(self.url("list")).content.decode()
        self.assertNotIn(self.url("add"), html)
