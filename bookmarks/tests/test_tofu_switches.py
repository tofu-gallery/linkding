# Tofu (2026-10-25): this file is Tofu's addition; it is not part of upstream linkding.
#
# The switches Tofu's settings (settings/tofu.py) turn on, tested on upstream's test settings, where they are off:
# each test with a switch on has one beside it showing upstream's behaviour with it off.
import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from bookmarks.services import tasks
from bookmarks.tests import test_settings_general_view as general_view_tests
from bookmarks.tests.helpers import BookmarkFactoryMixin
from bookmarks.views.settings import app_version, get_version_info

FILES_OFF = {"LD_DISABLE_FAVICONS": True, "LD_DISABLE_PREVIEW_IMAGES": True}


class TofuSwitchesTestCase(TestCase, BookmarkFactoryMixin):
    def sign_in(self, favicons=False, previews=False):
        user = self.get_or_create_test_user()
        user.profile.enable_favicons = favicons
        user.profile.enable_preview_images = previews
        user.profile.save()
        self.client.force_login(user)
        return user

    def settings_page(self):
        return self.client.get(reverse("linkding:settings.general")).content.decode()

    def test_settings_page_offers_favicons_and_previews_by_default(self):
        self.sign_in(favicons=True)
        html = self.settings_page()
        self.assertIn("Enable Favicons", html)
        self.assertIn("Refresh Favicons", html)
        self.assertIn("Enable Preview Images", html)

    @override_settings(**FILES_OFF)
    def test_settings_page_leaves_favicons_and_previews_out(self):
        self.sign_in(favicons=True)
        html = self.settings_page()
        self.assertNotIn("Enable Favicons", html)
        self.assertNotIn("Refresh Favicons", html)
        self.assertNotIn("Enable Preview Images", html)

    @override_settings(**FILES_OFF)
    def test_profile_form_cannot_turn_favicons_or_previews_on(self):
        user = self.sign_in()
        form_data = general_view_tests.SettingsGeneralViewTestCase.create_profile_form_data(
            self, {"enable_favicons": True, "enable_preview_images": True}
        )
        response = self.client.post(reverse("linkding:settings.update"), form_data)
        self.assertEqual(response.status_code, 302)
        user.profile.refresh_from_db()
        self.assertFalse(user.profile.enable_favicons)
        self.assertFalse(user.profile.enable_preview_images)

    @override_settings(LD_DISABLE_BACKGROUND_TASKS=False)
    def test_favicons_and_previews_load_by_default(self):
        user = self.sign_in(favicons=True, previews=True)
        self.assertTrue(tasks.is_favicon_feature_active(user))
        self.assertTrue(tasks.is_preview_feature_active(user))

    @override_settings(LD_DISABLE_BACKGROUND_TASKS=False, **FILES_OFF)
    def test_switches_load_no_favicon_or_preview(self):
        user = self.sign_in(favicons=True, previews=True)
        self.assertFalse(tasks.is_favicon_feature_active(user))
        self.assertFalse(tasks.is_preview_feature_active(user))

    def bookmark_list(self):
        self.sign_in(favicons=True, previews=True)
        bookmark = self.setup_bookmark(
            favicon_file="https_example_com.png", preview_image_file="preview_1.png"
        )
        index = reverse("linkding:bookmarks.index")
        return (
            self.client.get(index).content.decode(),
            self.client.get(f"{index}?details={bookmark.id}").content.decode(),
        )

    def test_list_and_details_show_favicons_and_previews_by_default(self):
        html, details = self.bookmark_list()
        self.assertIn("https_example_com.png", html)
        self.assertIn("preview_1.png", html)
        self.assertIn("https_example_com.png", details)

    @override_settings(**FILES_OFF)
    def test_list_and_details_show_no_favicon_or_preview(self):
        html, details = self.bookmark_list()
        self.assertNotIn("https_example_com.png", html)
        self.assertNotIn("preview_1.png", html)
        self.assertNotIn("https_example_com.png", details)
        self.assertNotIn("preview_1.png", details)

    def test_details_have_a_files_section_by_default(self):
        _, details = self.bookmark_list()
        self.assertIn("<h3>Files</h3>", details)

    @override_settings(LD_DISABLE_ASSET_UPLOAD=True, LD_ENABLE_SNAPSHOTS=False)
    def test_details_have_no_empty_files_section(self):
        _, details = self.bookmark_list()
        self.assertNotIn("<h3>Files</h3>", details)

    @override_settings(LD_DISABLE_VERSION_CHECK=True)
    def test_version_check_asks_nobody(self):
        get_version_info.cache_clear()
        try:
            with patch("bookmarks.views.settings.requests.get") as get:
                self.assertEqual(get_version_info(), app_version)
                get.assert_not_called()
        finally:
            get_version_info.cache_clear()

    def test_login_page_has_no_hint_by_default(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("has no account yet", html)

    @override_settings(LD_INITIAL_SUPERUSER_HINT=True)
    def test_login_page_hint_until_there_is_an_account(self):
        with patch.dict(os.environ, {"LD_SUPERUSER_NAME": ""}):
            html = self.client.get(reverse("login")).content.decode()
        self.assertIn("has no account yet", html)
        self.assertIn("<code>LD_SUPERUSER_PASSWORD</code>", html)
        self.assertIn("<code>admin</code>", html)

        with patch.dict(os.environ, {"LD_SUPERUSER_NAME": "frank"}):
            html = self.client.get(reverse("login")).content.decode()
        self.assertIn("<code>frank</code>", html)

        self.get_or_create_test_user()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("has no account yet", html)

    def test_close_data_api_does_nothing_without_postgresql(self):
        call_command("tofu_close_data_api")
