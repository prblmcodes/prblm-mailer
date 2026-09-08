"""Setup ergonomics: required_apps helper, URL bundle, checks, base-URL fallback."""
from django.test import SimpleTestCase, TestCase, override_settings

from prblm_mailer import required_apps, with_required_apps
from prblm_mailer.checks import check_prblm_mailer_settings


class RequiredAppsTests(SimpleTestCase):
    def test_with_required_apps_adds_and_dedupes(self):
        apps = with_required_apps(["anymail", "myapp"])   # anymail already present
        for expected in ("prblm_mailer", "newsletter", "sorl.thumbnail", "django.contrib.sites"):
            self.assertIn(expected, apps)
        self.assertEqual(apps.count("anymail"), 1)         # not duplicated
        self.assertIn("myapp", apps)                       # host apps kept

    def test_required_apps_list(self):
        self.assertIn("newsletter", required_apps())


class UrlBundleTests(SimpleTestCase):
    def test_bundle_mounts_three_paths(self):
        import prblm_mailer.urls_bundle as bundle
        self.assertEqual(len(bundle.urlpatterns), 3)


class ChecksTests(TestCase):
    # TestCase, not SimpleTestCase: the Site-domain check reads the sites table, and
    # a Site left in Django's SITE_CACHE by another test would otherwise decide the
    # result of "fully configured".
    def test_ok_when_configured(self):
        from django.contrib.sites.models import Site
        Site.objects.filter(pk=1).update(domain="configured.example.org")
        Site.objects.clear_cache()
        with override_settings(
            SITE_ID=1, WAGTAILADMIN_BASE_URL="http://x", NEWSLETTER_USE_HTTPS=False,
        ):
            self.assertEqual(check_prblm_mailer_settings(None), [])

    def test_warning_when_https_links_on_an_http_site(self):
        with override_settings(
            SITE_ID=1, WAGTAILADMIN_BASE_URL="http://localhost:8000", NEWSLETTER_USE_HTTPS=True,
        ):
            ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertIn("prblm_mailer.W003", ids)

    def test_error_without_site_id(self):
        with override_settings(SITE_ID=None):
            ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertIn("prblm_mailer.E001", ids)

    def test_warning_without_base_url(self):
        with override_settings(WAGTAILADMIN_BASE_URL=""):
            ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertIn("prblm_mailer.W001", ids)


class BaseUrlFallbackTests(TestCase):
    def test_uses_setting_when_present(self):
        with override_settings(WAGTAILADMIN_BASE_URL="https://ex.com/"):
            from prblm_mailer.sending import absolute_url
            self.assertEqual(absolute_url("/a"), "https://ex.com/a")

    def test_falls_back_to_wagtail_site(self):
        with override_settings(WAGTAILADMIN_BASE_URL=""):
            from prblm_mailer.sending import absolute_url
            url = absolute_url("/mailer/x/")
        self.assertTrue(url.startswith("http"))     # a real absolute URL, not a crash
        self.assertTrue(url.endswith("/mailer/x/"))


class SiteDomainTests(TestCase):
    """The opt-in link is built from the Site row, so a placeholder domain breaks it."""

    def test_warns_while_domain_is_the_placeholder(self):
        from django.contrib.sites.models import Site
        Site.objects.filter(pk=1).update(domain="example.com")
        Site.objects.clear_cache()
        with override_settings(SITE_ID=1, WAGTAILADMIN_BASE_URL="https://real.example.org"):
            ids = [i.id for i in check_prblm_mailer_settings(None)]
        self.assertIn("prblm_mailer.W002", ids)

    def test_placeholder_is_corrected_from_base_url(self):
        from django.contrib.sites.models import Site
        from prblm_mailer.subscriptions import _reconcile_site_domain
        Site.objects.filter(pk=1).update(domain="example.com")
        Site.objects.clear_cache()
        with override_settings(SITE_ID=1, WAGTAILADMIN_BASE_URL="http://localhost:8000"):
            _reconcile_site_domain()
        self.assertEqual(Site.objects.get(pk=1).domain, "localhost:8000")

    def test_a_real_domain_is_never_overwritten(self):
        from django.contrib.sites.models import Site
        from prblm_mailer.subscriptions import _reconcile_site_domain
        Site.objects.filter(pk=1).update(domain="chosen.example.org")
        Site.objects.clear_cache()
        with override_settings(SITE_ID=1, WAGTAILADMIN_BASE_URL="http://localhost:8000"):
            _reconcile_site_domain()
        self.assertEqual(Site.objects.get(pk=1).domain, "chosen.example.org")
