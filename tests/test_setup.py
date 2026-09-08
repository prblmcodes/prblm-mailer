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


class ChecksTests(SimpleTestCase):
    def test_ok_when_configured(self):
        with override_settings(SITE_ID=1, WAGTAILADMIN_BASE_URL="http://x"):
            self.assertEqual(check_prblm_mailer_settings(None), [])

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
