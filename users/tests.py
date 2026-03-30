"""
Unit and integration tests for users app.
Mocks Cloud Run and Supabase so you can test locally without credentials.

Run with: python manage.py test users
   or:    pytest
"""

from unittest.mock import patch, MagicMock
from io import BytesIO, StringIO

from PIL import Image
from django.core.management import call_command
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed

from users.services import validate_supabase_url, strip_exif
from users.authentication import SupabaseJWTAuthentication
from users.models import UserProfile

MOCK_CLOUD_RUN_URL = "https://lotus-model-test-uc.a.run.app"

MOCK_PREDICTIONS = {
    "predictions": [
        {
            "species_id": "1362954",
            "name": "Schefflera actinophylla",
            "confidence": 0.8732,
        },
        {
            "species_id": "1363004",
            "name": "Heptapleurum arboricola",
            "confidence": 0.0521,
        },
        {"species_id": "1361853", "name": "Fatsia japonica", "confidence": 0.0198},
        {"species_id": "1362001", "name": "Tetrapanax papyrifer", "confidence": 0.0112},
        {"species_id": "1363901", "name": "Polyscias fruticosa", "confidence": 0.0087},
    ]
}

VALID_IMAGE_URL = (
    "https://myproject.supabase.co/storage/v1/object/public/plants/img.jpg"
)
VALID_SIGNED_URL = (
    "https://myproject.supabase.co/storage/v1/object/sign/plants/img.jpg?token=abc123"
)

MOCK_UPLOAD_ROW = {
    "id": "a1b2c3d4-0000-0000-0000-000000000001",
    "user_id": "gallery-uid",
    "bucket": "plant-images",
    "storage_path": "gallery-uid/upload.jpg",
    "original_name": "photo.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 1234,
    "status": "uploaded",
    "created_at": "2026-03-27T18:00:00+00:00",
}

MOCK_SCAN_ROW = {
    "id": 1,
    "upload_id": "a1b2c3d4-0000-0000-0000-000000000001",
    "user_id": "scanner-uid",
    "plant_name": "Tomato",
    "image_url": "https://myproject.supabase.co/storage/v1/img.jpg",
    "supabase_path": "uid-up/scan.jpg",
    "top_predictions": [],
    "disease_name": "Healthy",
    "disease_id": None,
    "confidence": None,
    "disease_genus": "",
    "all_diseases": [],
    "created_at": "2026-03-27T18:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Unit tests — validate_supabase_url
# ---------------------------------------------------------------------------
class ValidateSupabaseUrlTests(TestCase):
    """Unit tests for the URL validation helper."""

    def test_accepts_public_supabase_url(self):
        validate_supabase_url(VALID_IMAGE_URL)  # should not raise

    def test_accepts_signed_supabase_url(self):
        validate_supabase_url(VALID_SIGNED_URL)  # should not raise

    def test_rejects_http_url(self):
        with self.assertRaises(ValueError) as ctx:
            validate_supabase_url(
                "http://myproject.supabase.co/storage/v1/object/public/plants/img.jpg"
            )
        self.assertIn("HTTPS", str(ctx.exception))

    def test_rejects_non_supabase_domain(self):
        with self.assertRaises(ValueError) as ctx:
            validate_supabase_url("https://evil.com/malicious.jpg")
        self.assertIn("supabase.co", str(ctx.exception))

    def test_rejects_supabase_subdomain_spoof(self):
        with self.assertRaises(ValueError) as ctx:
            validate_supabase_url("https://supabase.co.evil.com/img.jpg")
        self.assertIn("supabase.co", str(ctx.exception))

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            validate_supabase_url("")


# ---------------------------------------------------------------------------
# Integration tests — POST /api/predict/
# ---------------------------------------------------------------------------


@override_settings(CLOUD_RUN_URL=MOCK_CLOUD_RUN_URL)
class PredictEndpointTests(TestCase):
    """Tests for POST /api/predict/"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_authenticate(user=self.user)

    def test_predict_requires_authentication(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_with_valid_image_url(self, mock_token, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_PREDICTIONS
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("predictions", resp.json())
        self.assertEqual(len(resp.json()["predictions"]), 5)

        # Verify Cloud Run was called with correct auth
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(
            call_kwargs.kwargs["headers"]["Authorization"], "Bearer mock-token"
        )

    def test_predict_rejects_non_supabase_url(self):
        resp = self.client.post(
            "/api/predict/",
            {"image_url": "https://evil.com/malicious.jpg"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supabase.co", resp.json()["error"])

    def test_predict_rejects_http_url(self):
        resp = self.client.post(
            "/api/predict/",
            {"image_url": "http://myproject.supabase.co/img.jpg"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("HTTPS", resp.json()["error"])

    def test_predict_missing_image_url(self):
        resp = self.client.post("/api/predict/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", resp.json())

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_cloud_run_error(self, mock_token, mock_post):
        import requests as req_lib

        mock_post.return_value.raise_for_status.side_effect = req_lib.HTTPError(
            "Cloud Run error"
        )

        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # Django test runner sets DEBUG=False, so generic message is returned
        self.assertEqual(resp.json()["error"], "Inference service unavailable")

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_with_signed_supabase_url(self, mock_token, mock_post):
        """Signed (private bucket) URLs should also be accepted."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_PREDICTIONS
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_SIGNED_URL}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("predictions", resp.json())

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_returns_five_predictions(self, mock_token, mock_post):
        """Response should contain exactly 5 predictions."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_PREDICTIONS
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )
        predictions = resp.json()["predictions"]
        self.assertEqual(len(predictions), 5)
        # Each prediction has required keys
        for p in predictions:
            self.assertIn("species_id", p)
            self.assertIn("name", p)
            self.assertIn("confidence", p)

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_cloud_run_timeout(self, mock_token, mock_post):
        """Timeout from Cloud Run should return 500."""
        import requests as req_lib

        mock_post.side_effect = req_lib.Timeout("Connection timed out")

        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


@override_settings(CLOUD_RUN_URL="")
class PredictMissingConfigTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser2", email="test2@example.com", password="testpass123"
        )
        self.client.force_authenticate(user=self.user)

    def test_predict_fails_without_cloud_run_url(self):
        resp = self.client.post(
            "/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("CLOUD_RUN_URL", resp.json()["error"])


# ---------------------------------------------------------------------------
# Helper: create a minimal in-memory image for upload tests
# ---------------------------------------------------------------------------
def _make_test_image(fmt="PNG", size=(10, 10), mode="RGB"):
    img = Image.new(mode, size, color="red")
    buf = BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    buf.name = "test.png"
    return buf


# ---------------------------------------------------------------------------
# SupabaseJWTAuthentication tests
# ---------------------------------------------------------------------------
@override_settings(SUPABASE_URL="https://test.supabase.co")
class SupabaseJWTAuthenticationTests(TestCase):
    """Tests for the custom Supabase JWT authentication backend."""

    def setUp(self):
        self.auth = SupabaseJWTAuthentication()
        self.factory = APIRequestFactory()

    def test_no_auth_header_returns_none(self):
        request = self.factory.get("/api/me/")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_non_bearer_header_returns_none(self):
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Basic abc123")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    @override_settings(SUPABASE_URL="")
    def test_missing_supabase_url_raises(self):
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer some-token")
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("SUPABASE_URL", str(ctx.exception))

    @patch("users.authentication._get_jwks_client")
    def test_expired_token_raises(self, mock_client):
        import jwt as pyjwt

        mock_client.return_value.get_signing_key_from_jwt.side_effect = (
            pyjwt.ExpiredSignatureError("expired")
        )
        request = self.factory.get(
            "/api/me/", HTTP_AUTHORIZATION="Bearer expired-token"
        )
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("expired", str(ctx.exception))

    @patch("users.authentication._get_jwks_client")
    def test_invalid_token_raises(self, mock_client):
        import jwt as pyjwt

        mock_client.return_value.get_signing_key_from_jwt.side_effect = (
            pyjwt.InvalidTokenError("bad token")
        )
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer bad-token")
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("Invalid token", str(ctx.exception))

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_missing_sub_claim_raises(self, mock_client, mock_decode):
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {"email": "a@b.com"}  # no "sub"
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer token")
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("sub", str(ctx.exception))

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_valid_token_creates_user(self, mock_client, mock_decode):
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "uid-123",
            "email": "new@example.com",
            "user_metadata": {},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer valid-token")
        user, payload = self.auth.authenticate(request)
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.username, "new")
        self.assertTrue(UserProfile.objects.filter(supabase_uid="uid-123").exists())
        self.assertFalse(user.has_usable_password())

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_existing_user_returned(self, mock_client, mock_decode):
        user = User.objects.create_user(username="existing", email="e@example.com")
        UserProfile.objects.create(user=user, supabase_uid="uid-exist")
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "uid-exist",
            "email": "e@example.com",
            "user_metadata": {},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer valid-token")
        returned_user, _ = self.auth.authenticate(request)
        self.assertEqual(returned_user.pk, user.pk)

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_username_from_metadata(self, mock_client, mock_decode):
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "uid-meta",
            "email": "m@example.com",
            "user_metadata": {"username": "chosenname"},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer token")
        user, _ = self.auth.authenticate(request)
        self.assertEqual(user.username, "chosenname")

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_username_from_full_name(self, mock_client, mock_decode):
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "uid-fn",
            "email": "fn@example.com",
            "user_metadata": {"full_name": "John Doe"},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer token")
        user, _ = self.auth.authenticate(request)
        self.assertEqual(user.username, "John Doe")

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_username_collision_increments(self, mock_client, mock_decode):
        User.objects.create_user(username="taken", email="t1@example.com")
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "uid-col",
            "email": "taken@example.com",
            "user_metadata": {},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer token")
        user, _ = self.auth.authenticate(request)
        self.assertEqual(user.username, "taken_1")

    @patch("users.authentication.jwt.decode")
    @patch("users.authentication._get_jwks_client")
    def test_username_fallback_to_uid(self, mock_client, mock_decode):
        mock_key = MagicMock()
        mock_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = {
            "sub": "abcd1234-rest",
            "email": "",
            "user_metadata": {},
        }
        request = self.factory.get("/api/me/", HTTP_AUTHORIZATION="Bearer token")
        user, _ = self.auth.authenticate(request)
        self.assertEqual(user.username, "abcd1234")

    def test_authenticate_header(self):
        request = self.factory.get("/api/me/")
        self.assertEqual(self.auth.authenticate_header(request), "Bearer")


# ---------------------------------------------------------------------------
# View tests — public endpoints
# ---------------------------------------------------------------------------
class PublicEndpointTests(TestCase):
    """Tests for unauthenticated endpoints."""

    def setUp(self):
        self.client = APIClient()

    def test_home_returns_greeting(self):
        resp = self.client.get("/api/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("Hello", resp.data)

    def test_get_message_returns_dict(self):
        resp = self.client.get("/api/message/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("message", resp.data)


# ---------------------------------------------------------------------------
# View tests — get_current_user
# ---------------------------------------------------------------------------
class GetCurrentUserTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="viewer", email="viewer@test.com")
        self.auth_payload = {"sub": "supabase-uid-viewer"}

    def test_returns_user_data(self):
        self.client.force_authenticate(user=self.user, token=self.auth_payload)
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], "supabase-uid-viewer")
        self.assertEqual(resp.data["username"], "viewer")
        self.assertEqual(resp.data["email"], "viewer@test.com")
        self.assertEqual(resp.data["display_name"], "viewer")
        self.assertEqual(resp.data["settings"]["theme"], "auto")

    def test_requires_auth(self):
        resp = self.client.get("/api/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# View tests — update_profile
# ---------------------------------------------------------------------------
class UpdateProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="updater", email="up@test.com")
        self.auth_payload = {"sub": "supabase-uid-updater"}
        self.client.force_authenticate(user=self.user, token=self.auth_payload)

    def test_update_username(self):
        resp = self.client.patch(
            "/api/me/profile/", {"username": "newname"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["username"], "newname")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newname")

    def test_update_display_name(self):
        resp = self.client.patch(
            "/api/me/profile/",
            {"display_name": "Green Thumb"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["display_name"], "Green Thumb")
        self.assertEqual(self.user.profile.display_name, "Green Thumb")

    def test_missing_fields_returns_400(self):
        resp = self.client.patch("/api/me/profile/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("At least one", resp.data["error"])

    def test_duplicate_username_returns_400(self):
        User.objects.create_user(username="taken_name", email="other@test.com")
        resp = self.client.patch(
            "/api/me/profile/", {"username": "taken_name"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already taken", resp.data["error"])

    def test_keep_own_username(self):
        resp = self.client.patch(
            "/api/me/profile/", {"username": "updater"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.patch("/api/me/profile/", {"username": "x"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class UserSettingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="settings", email="settings@test.com"
        )
        UserProfile.objects.create(user=self.user, supabase_uid="settings-uid")
        self.auth_payload = {"sub": "settings-uid"}
        self.client.force_authenticate(user=self.user, token=self.auth_payload)

    def test_get_settings(self):
        resp = self.client.get("/api/me/settings/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["theme"], "auto")
        self.assertEqual(resp.data["notifications"]["enabled"], True)

    def test_patch_settings(self):
        resp = self.client.patch(
            "/api/me/settings/",
            {
                "theme": "dark",
                "notifications": {
                    "enabled": False,
                    "scan_reminders": False,
                },
                "privacy": {
                    "share_data": True,
                    "analytics_enabled": False,
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["theme"], "dark")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme_preference, "dark")
        self.assertEqual(self.user.profile.notifications_enabled, False)
        self.assertEqual(self.user.profile.scan_reminders_enabled, False)
        self.assertEqual(self.user.profile.share_data, True)
        self.assertEqual(self.user.profile.analytics_enabled, False)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.patch("/api/me/settings/", {"theme": "dark"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class UserAvatarTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="avatar", email="avatar@test.com")
        UserProfile.objects.create(user=self.user, supabase_uid="avatar-uid")
        self.auth_payload = {"sub": "avatar-uid"}
        self.client.force_authenticate(user=self.user, token=self.auth_payload)

    @patch(
        "users.views.serialize_user_profile",
        return_value={
            "id": "avatar-uid",
            "username": "avatar",
            "email": "avatar@test.com",
            "display_name": "avatar",
            "avatar_url": "https://signed/avatar.jpg",
            "joined_at": "2026-03-29T00:00:00+00:00",
            "settings": {
                "theme": "auto",
                "notifications": {
                    "enabled": True,
                    "scan_reminders": True,
                    "care_reminders": True,
                },
                "privacy": {
                    "share_data": False,
                    "analytics_enabled": True,
                },
            },
        },
    )
    @patch("users.views.upload_profile_avatar")
    def test_upload_avatar(self, mock_upload_avatar, _mock_serialize_profile):
        image = _make_test_image()
        resp = self.client.post("/api/me/avatar/", {"image": image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_upload_avatar.assert_called_once()
        self.assertEqual(resp.data["avatar_url"], "https://signed/avatar.jpg")

    @patch("users.views.delete_profile_avatar")
    def test_delete_avatar(self, mock_delete_profile_avatar):
        resp = self.client.delete("/api/me/avatar/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        mock_delete_profile_avatar.assert_called_once_with(self.user, "avatar-uid")


# ---------------------------------------------------------------------------
# View tests — upload_image
# ---------------------------------------------------------------------------
class UploadImageTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="uploader", email="up@test.com")
        UserProfile.objects.create(user=self.user, supabase_uid="uid-up")
        self.client.force_authenticate(user=self.user)

    def test_missing_image_returns_400(self):
        resp = self.client.post("/api/images/upload/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No image", resp.data["error"])

    @patch("users.views.serialize_upload")
    @patch("users.views.upload_plant_image")
    def test_successful_upload(self, mock_upload, mock_serialize):
        mock_upload.return_value = MOCK_UPLOAD_ROW
        mock_serialize.return_value = {
            "id": MOCK_UPLOAD_ROW["id"],
            "supabase_path": "uid-up/img.jpg",
        }

        image = _make_test_image()
        resp = self.client.post(
            "/api/images/upload/", {"image": image}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        mock_upload.assert_called_once()

    @patch("users.views.upload_plant_image", side_effect=Exception("boom"))
    @override_settings(DEBUG=False)
    def test_upload_failure_returns_500(self, mock_upload):
        image = _make_test_image()
        resp = self.client.post(
            "/api/images/upload/", {"image": image}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(resp.data["error"], "Image upload failed")

    @patch("users.views.upload_plant_image", side_effect=Exception("boom"))
    @override_settings(DEBUG=True)
    def test_upload_failure_debug_shows_detail(self, mock_upload):
        image = _make_test_image()
        resp = self.client.post(
            "/api/images/upload/", {"image": image}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("boom", resp.data["error"])

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        image = _make_test_image()
        resp = self.client.post(
            "/api/images/upload/", {"image": image}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# View tests — scan management (via Supabase client)
# ---------------------------------------------------------------------------
class ScanManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="scanner", email="scan@test.com")
        UserProfile.objects.create(user=self.user, supabase_uid="scanner-uid")
        self.client.force_authenticate(user=self.user)
        cache.clear()

    @patch(
        "users.serializers.get_signed_image_urls",
        return_value={
            "url": "https://signed/url",
            "thumbnail_url": "https://signed/thumb",
            "expires_at": "2026-03-30T18:00:00+00:00",
        },
    )
    @patch("users.views.find_upload_by_path")
    @patch("users.views.promote_upload_to_retained")
    @patch("users.views.get_supabase_client")
    def test_save_scan(
        self, mock_get_client, mock_promote_upload, mock_find_upload_by_path, _mock_url
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_find_upload_by_path.return_value = {
            "id": "upload-uuid-1",
            "retention_state": "ephemeral",
            "expires_at": "2026-03-30T18:00:00+00:00",
        }

        # Mock disease lookup (no match)
        mock_client.table.return_value.select.return_value.ilike.return_value.ilike.return_value.limit.return_value.execute.return_value.data = (  # noqa: E501
            []
        )
        # Mock insert
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            MOCK_SCAN_ROW
        ]

        resp = self.client.post(
            "/api/scans/",
            {
                "plant_name": "Tomato",
                "image_url": VALID_IMAGE_URL,
                "supabase_path": "uid-up/scan.jpg",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["plant_name"], "Tomato")
        mock_promote_upload.assert_called_once_with("upload-uuid-1")

    @patch("users.views.reset_upload_to_ephemeral")
    @patch("users.views.promote_upload_to_retained")
    @patch("users.views.get_supabase_client")
    @patch("users.views.find_upload_by_path")
    def test_save_scan_resets_ephemeral_upload_if_insert_fails(
        self,
        mock_find_upload_by_path,
        mock_get_client,
        mock_promote_upload,
        mock_reset_upload,
    ):
        mock_find_upload_by_path.return_value = {
            "id": "upload-uuid-2",
            "retention_state": "ephemeral",
            "expires_at": "2026-03-30T18:00:00+00:00",
        }
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.ilike.return_value.ilike.return_value.limit.return_value.execute.return_value.data = (  # noqa: E501
            []
        )
        mock_client.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("insert failed")
        )

        with self.assertRaises(RuntimeError):
            self.client.post(
                "/api/scans/",
                {
                    "plant_name": "Tomato",
                    "image_url": VALID_IMAGE_URL,
                    "supabase_path": "uid-up/scan.jpg",
                },
                format="json",
            )

        mock_promote_upload.assert_called_once_with("upload-uuid-2")
        mock_reset_upload.assert_called_once_with("upload-uuid-2")

    @patch(
        "users.serializers.get_signed_image_urls",
        return_value={
            "url": "https://signed/url",
            "thumbnail_url": "https://signed/thumb",
            "expires_at": "2026-03-30T18:00:00+00:00",
        },
    )
    @patch("users.views.get_supabase_client")
    def test_scan_history(self, mock_get_client, _mock_url):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [  # noqa: E501
            MOCK_SCAN_ROW
        ]

        resp = self.client.get("/api/scans/list/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["thumbnail_url"], "https://signed/thumb")

    @patch(
        "users.serializers.get_signed_image_urls",
        return_value={
            "url": "https://signed/url",
            "thumbnail_url": "https://signed/thumb",
            "expires_at": "2026-03-30T18:00:00+00:00",
        },
    )
    @patch("users.views.get_supabase_client")
    def test_scan_detail_get(self, mock_get_client, _mock_url):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [  # noqa: E501
            MOCK_SCAN_ROW
        ]

        resp = self.client.get("/api/scans/1/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["plant_name"], "Tomato")
        self.assertEqual(resp.data["thumbnail_url"], "https://signed/thumb")

    @patch("users.views.get_supabase_client")
    def test_delete_scan(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [  # noqa: E501
            MOCK_SCAN_ROW
        ]
        mock_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = (  # noqa: E501
            MagicMock()
        )

        resp = self.client.delete("/api/scans/1/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    @patch("users.views.get_supabase_client")
    def test_delete_other_users_scan_returns_404(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        # With direct user_id filter, querying another user's scan returns empty
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (  # noqa: E501
            []
        )

        resp = self.client.delete("/api/scans/99/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @patch("users.views.get_supabase_client")
    def test_scan_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (  # noqa: E501
            []
        )

        resp = self.client.get("/api/scans/999/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# View tests — upload management (via Supabase client)
# ---------------------------------------------------------------------------
class UploadManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="gallery",
            email="gallery@test.com",
        )
        UserProfile.objects.create(user=self.user, supabase_uid="gallery-uid")
        self.client.force_authenticate(user=self.user)
        cache.clear()

    @patch("users.serializers.check_upload_in_use", return_value=False)
    @patch(
        "users.serializers.get_signed_image_urls",
        return_value={
            "url": "https://signed/url",
            "thumbnail_url": "https://signed/thumb",
            "expires_at": "2026-03-30T18:00:00+00:00",
        },
    )
    @patch("users.views.get_supabase_client")
    def test_list_uploads(self, mock_get_client, _mock_url, _mock_in_use):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.data = [MOCK_UPLOAD_ROW]
        mock_resp.count = 1
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = (  # noqa: E501
            mock_resp
        )

        resp = self.client.get("/api/images/list/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], MOCK_UPLOAD_ROW["id"])
        self.assertFalse(results[0]["in_use"])
        self.assertEqual(results[0]["thumbnail_url"], "https://signed/thumb")

    @patch("users.views.check_upload_in_use", return_value=False)
    @patch("users.views.delete_storage_object")
    @patch("users.views.get_supabase_client")
    def test_delete_unused_upload(
        self, mock_get_client, mock_delete_storage, _mock_in_use
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [  # noqa: E501
            MOCK_UPLOAD_ROW
        ]

        upload_id = MOCK_UPLOAD_ROW["id"]
        resp = self.client.delete(f"/api/images/{upload_id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        mock_delete_storage.assert_called_once_with("gallery-uid/upload.jpg")

    @patch("users.views.check_upload_in_use", return_value=True)
    @patch("users.views.delete_storage_object")
    @patch("users.views.get_supabase_client")
    def test_delete_upload_in_use_returns_conflict(
        self, mock_get_client, mock_delete_storage, _mock_in_use
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [  # noqa: E501
            MOCK_UPLOAD_ROW
        ]

        upload_id = MOCK_UPLOAD_ROW["id"]
        resp = self.client.delete(f"/api/images/{upload_id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Delete that scan first", resp.data["error"])
        mock_delete_storage.assert_not_called()

    @patch("users.views.get_supabase_client")
    def test_delete_missing_upload_returns_404(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (  # noqa: E501
            []
        )

        resp = self.client.delete("/api/images/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Service tests — strip_exif
# ---------------------------------------------------------------------------
class StripExifTests(TestCase):
    def test_strips_and_converts_to_jpeg(self):
        image = _make_test_image(fmt="PNG")
        result = strip_exif(image)
        self.assertIsInstance(result, BytesIO)
        output_img = Image.open(result)
        self.assertEqual(output_img.format, "JPEG")

    def test_rgba_converted_to_rgb(self):
        image = _make_test_image(fmt="PNG", mode="RGBA")
        result = strip_exif(image)
        output_img = Image.open(result)
        self.assertEqual(output_img.mode, "RGB")

    def test_palette_mode_converted(self):
        image = _make_test_image(fmt="PNG", mode="P")
        result = strip_exif(image)
        output_img = Image.open(result)
        self.assertEqual(output_img.mode, "RGB")


# ---------------------------------------------------------------------------
# Service tests — upload_plant_image
# ---------------------------------------------------------------------------
class UploadPlantImageServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="svc_user", email="svc@test.com")
        UserProfile.objects.create(user=self.user, supabase_uid="svc-uid")
        cache.clear()

    @patch("users.services.get_supabase_client")
    def test_upload_creates_record(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_storage = MagicMock()
        mock_client.storage.from_.return_value = mock_storage
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {
                "id": "new-uuid",
                "user_id": "svc-uid",
                "bucket": "plant-images",
                "storage_path": "svc-uid/test.jpg",
                "original_name": "photo.png",
                "mime_type": "image/jpeg",
                "size_bytes": 100,
                "status": "uploaded",
                "created_at": "2026-03-27T18:00:00+00:00",
            }
        ]

        from users.services import upload_plant_image

        image = _make_test_image()
        result = upload_plant_image(self.user, image, "photo.png")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["storage_path"].startswith("svc-uid/"))
        self.assertEqual(result["original_name"], "photo.png")
        mock_storage.upload.assert_called_once()
        insert_payload = mock_client.table.return_value.insert.call_args.args[0]
        self.assertEqual(insert_payload["retention_state"], "ephemeral")
        self.assertTrue(insert_payload["expires_at"])


# ---------------------------------------------------------------------------
# Service tests — get_image_url
# ---------------------------------------------------------------------------
class GetImageUrlTests(TestCase):
    @patch("users.services.get_supabase_client")
    def test_returns_signed_url(self, mock_get_client):
        from users.services import get_image_url

        cache.clear()
        mock_storage = MagicMock()
        mock_storage.create_signed_url.return_value = {
            "signedURL": "https://signed.example.com/img"
        }
        mock_get_client.return_value.storage.from_.return_value = mock_storage

        url = get_image_url("uid/img.jpg")
        self.assertEqual(url, "https://signed.example.com/img")
        mock_storage.create_signed_url.assert_called_once_with(
            path="uid/img.jpg", expires_in=86400, options={}
        )

    @patch("users.services.get_supabase_client")
    def test_reuses_cached_signed_url(self, mock_get_client):
        from users.services import get_image_url

        cache.clear()
        mock_storage = MagicMock()
        mock_storage.create_signed_url.return_value = {
            "signedURL": "https://signed.example.com/img"
        }
        mock_get_client.return_value.storage.from_.return_value = mock_storage

        first_url = get_image_url("uid/img.jpg")
        second_url = get_image_url("uid/img.jpg")

        self.assertEqual(first_url, second_url)
        mock_storage.create_signed_url.assert_called_once()

    @patch("users.services.get_supabase_client")
    def test_get_signed_image_urls_returns_thumbnail(self, mock_get_client):
        from users.services import get_signed_image_urls

        cache.clear()
        mock_storage = MagicMock()
        mock_storage.create_signed_url.side_effect = [
            {"signedURL": "https://signed.example.com/full"},
            {"signedURL": "https://signed.example.com/thumb"},
        ]
        mock_get_client.return_value.storage.from_.return_value = mock_storage

        urls = get_signed_image_urls("uid/img.jpg")

        self.assertEqual(urls["url"], "https://signed.example.com/full")
        self.assertEqual(urls["thumbnail_url"], "https://signed.example.com/thumb")
        self.assertTrue(urls["expires_at"])
        mock_storage.create_signed_url.assert_any_call(
            path="uid/img.jpg", expires_in=86400, options={}
        )
        mock_storage.create_signed_url.assert_any_call(
            path="uid/img.jpg",
            expires_in=86400,
            options={
                "transform": {
                    "width": 256,
                    "height": 256,
                    "resize": "cover",
                    "quality": 80,
                }
            },
        )


# ---------------------------------------------------------------------------
# Management command tests — cleanup_ephemeral_uploads
# ---------------------------------------------------------------------------
class CleanupEphemeralUploadsCommandTests(TestCase):
    @patch(
        (
            "users.management.commands.cleanup_ephemeral_uploads."
            "get_uploads_ready_for_cleanup"
        )
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.mark_upload_as_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.claim_expired_uploads")
    def test_cleanup_stages_expired_ephemeral_uploads(
        self,
        mock_claim_expired,
        mock_mark_deleting,
        mock_ready_for_cleanup,
    ):
        mock_claim_expired.return_value = [
            {
                "id": "upload-1",
                "storage_path": "scanner-uid/upload-1.jpg",
                "user_id": "scanner-uid",
                "expires_at": "2026-03-29T00:00:00+00:00",
                "retention_state": "ephemeral",
            }
        ]
        mock_mark_deleting.return_value = True
        mock_ready_for_cleanup.return_value = []

        out = StringIO()
        call_command("cleanup_ephemeral_uploads", stdout=out)

        mock_mark_deleting.assert_called_once_with("upload-1")
        self.assertIn("staged=1", out.getvalue())

    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.reset_upload_to_ephemeral"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.delete_upload_record")
    @patch("users.management.commands.cleanup_ephemeral_uploads.delete_storage_object")
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.upload_is_still_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.check_upload_in_use")
    @patch(
        (
            "users.management.commands.cleanup_ephemeral_uploads."
            "get_uploads_ready_for_cleanup"
        )
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.mark_upload_as_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.claim_expired_uploads")
    def test_cleanup_deletes_ready_unreferenced_upload(
        self,
        mock_claim_expired,
        mock_mark_deleting,
        mock_ready_for_cleanup,
        mock_check_in_use,
        mock_still_deleting,
        mock_delete_storage,
        mock_delete_record,
        mock_reset,
    ):
        mock_claim_expired.return_value = []
        mock_ready_for_cleanup.return_value = [
            {
                "id": "upload-1",
                "storage_path": "scanner-uid/upload-1.jpg",
                "user_id": "scanner-uid",
                "expires_at": "2026-03-29T00:00:00+00:00",
                "retention_state": "deleting",
            }
        ]
        mock_check_in_use.return_value = False
        mock_still_deleting.return_value = True

        out = StringIO()
        call_command("cleanup_ephemeral_uploads", stdout=out)

        mock_mark_deleting.assert_not_called()
        mock_delete_storage.assert_called_once_with("scanner-uid/upload-1.jpg")
        mock_delete_record.assert_called_once_with("upload-1")
        mock_reset.assert_not_called()
        self.assertIn("deleted=1", out.getvalue())

    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.reset_upload_to_ephemeral"
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.promote_upload_to_retained"
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.upload_is_still_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.check_upload_in_use")
    @patch(
        (
            "users.management.commands.cleanup_ephemeral_uploads."
            "get_uploads_ready_for_cleanup"
        )
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.mark_upload_as_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.claim_expired_uploads")
    def test_cleanup_retains_referenced_upload(
        self,
        mock_claim_expired,
        mock_mark_deleting,
        mock_ready_for_cleanup,
        mock_check_in_use,
        mock_still_deleting,
        mock_promote_retained,
        mock_reset,
    ):
        mock_claim_expired.return_value = []
        mock_ready_for_cleanup.return_value = [
            {
                "id": "upload-2",
                "storage_path": "scanner-uid/upload-2.jpg",
                "user_id": "scanner-uid",
                "expires_at": "2026-03-29T00:00:00+00:00",
                "retention_state": "deleting",
            }
        ]
        mock_check_in_use.return_value = True
        mock_still_deleting.return_value = True

        out = StringIO()
        call_command("cleanup_ephemeral_uploads", stdout=out)

        mock_promote_retained.assert_called_once_with("upload-2")
        mock_reset.assert_not_called()
        self.assertIn("retained=1", out.getvalue())

    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.reset_upload_to_ephemeral"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.delete_upload_record")
    @patch("users.management.commands.cleanup_ephemeral_uploads.delete_storage_object")
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.upload_is_still_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.check_upload_in_use")
    @patch(
        (
            "users.management.commands.cleanup_ephemeral_uploads."
            "get_uploads_ready_for_cleanup"
        )
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.mark_upload_as_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.claim_expired_uploads")
    def test_cleanup_dry_run_does_not_delete(
        self,
        mock_claim_expired,
        mock_mark_deleting,
        mock_ready_for_cleanup,
        mock_check_in_use,
        mock_still_deleting,
        mock_delete_storage,
        mock_delete_record,
        mock_reset,
    ):
        mock_claim_expired.return_value = []
        mock_ready_for_cleanup.return_value = [
            {
                "id": "upload-3",
                "storage_path": "scanner-uid/upload-3.jpg",
                "user_id": "scanner-uid",
                "expires_at": "2026-03-29T00:00:00+00:00",
                "retention_state": "deleting",
            }
        ]
        mock_check_in_use.return_value = False
        mock_still_deleting.return_value = True

        out = StringIO()
        call_command("cleanup_ephemeral_uploads", "--dry-run", stdout=out)

        mock_delete_storage.assert_not_called()
        mock_delete_record.assert_not_called()
        mock_reset.assert_called_once_with("upload-3")
        self.assertIn("[dry-run] would delete upload upload-3", out.getvalue())

    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.reset_upload_to_ephemeral"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.delete_storage_object")
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.upload_is_still_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.check_upload_in_use")
    @patch(
        (
            "users.management.commands.cleanup_ephemeral_uploads."
            "get_uploads_ready_for_cleanup"
        )
    )
    @patch(
        "users.management.commands.cleanup_ephemeral_uploads.mark_upload_as_deleting"
    )
    @patch("users.management.commands.cleanup_ephemeral_uploads.claim_expired_uploads")
    def test_cleanup_resets_state_after_failure(
        self,
        mock_claim_expired,
        mock_mark_deleting,
        mock_ready_for_cleanup,
        mock_check_in_use,
        mock_still_deleting,
        mock_delete_storage,
        mock_reset,
    ):
        mock_claim_expired.return_value = []
        mock_ready_for_cleanup.return_value = [
            {
                "id": "upload-4",
                "storage_path": "scanner-uid/upload-4.jpg",
                "user_id": "scanner-uid",
                "expires_at": "2026-03-29T00:00:00+00:00",
                "retention_state": "deleting",
            }
        ]
        mock_check_in_use.return_value = False
        mock_still_deleting.return_value = True
        mock_delete_storage.side_effect = RuntimeError("bucket failure")

        err = StringIO()
        call_command("cleanup_ephemeral_uploads", stderr=err)

        mock_reset.assert_called_once_with("upload-4")
        self.assertIn("Failed to clean upload upload-4", err.getvalue())


# ---------------------------------------------------------------------------
# supabase.py — get_supabase_client
# ---------------------------------------------------------------------------
class GetSupabaseClientTests(TestCase):
    @override_settings(SUPABASE_URL="", SUPABASE_KEY="some-key")
    def test_missing_url_raises(self):
        from users.supabase import get_supabase_client

        with self.assertRaises(ValueError) as ctx:
            get_supabase_client()
        self.assertIn("not configured", str(ctx.exception))

    @override_settings(SUPABASE_URL="https://x.supabase.co", SUPABASE_KEY="")
    def test_missing_key_raises(self):
        from users.supabase import get_supabase_client

        with self.assertRaises(ValueError) as ctx:
            get_supabase_client()
        self.assertIn("not configured", str(ctx.exception))
