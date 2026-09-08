"""Phase 1: the package loads standalone, with no beMore reference."""
from django.test import SimpleTestCase


class SkeletonTests(SimpleTestCase):
    def test_app_imports(self):
        import prblm_mailer  # noqa: F401

    def test_conf_default_comes_through(self):
        from prblm_mailer.conf import get_setting
        self.assertEqual(get_setting("BRAND_COLOR"), "#2b6cb0")

    def test_host_override_wins(self):
        from prblm_mailer.conf import get_setting
        self.assertEqual(get_setting("FROM_EMAIL"), "test@example.com")

    def test_dry_run_follows_debug_when_unset(self):
        from django.test import override_settings
        from prblm_mailer.conf import get_setting

        # DRY_RUN default is None -> resolves to DEBUG. The test runner forces
        # DEBUG=False, so pin it explicitly to prove both branches.
        with override_settings(DEBUG=True):
            self.assertIs(get_setting("DRY_RUN"), True)
        with override_settings(DEBUG=False):
            self.assertIs(get_setting("DRY_RUN"), False)

    def test_app_is_installed(self):
        from django.apps import apps
        self.assertTrue(apps.is_installed("prblm_mailer"))
