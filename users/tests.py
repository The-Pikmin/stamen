"""
Unit and integration tests for users app.
Mocks Cloud Run and Supabase so you can test locally without credentials.

Run with: python manage.py test users
   or:    pytest
"""

from unittest.mock import patch, MagicMock
from io import BytesIO

from PIL import Image
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
        self.assertEqual(user.username, "john_doe")

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

    def test_missing_username_returns_400(self):
        resp = self.client.patch("/api/me/profile/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", resp.data["error"])

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

    @patch("users.views.upload_plant_image")
    @patch("users.views.PlantImageSerializer")
    def test_successful_upload(self, mock_serializer, mock_upload):
        from users.models import PlantImage

        plant_img = PlantImage(id=1, user=self.user, supabase_path="uid-up/img.jpg")
        mock_upload.return_value = plant_img
        mock_serializer.return_value.data = {
            "id": 1,
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

    @patch("users.services.get_supabase_client")
    def test_upload_creates_record(self, mock_get_client):
        mock_storage = MagicMock()
        mock_get_client.return_value.storage.from_.return_value = mock_storage

        from users.services import upload_plant_image

        image = _make_test_image()
        result = upload_plant_image(self.user, image, "photo.png")

        self.assertIsNotNone(result.pk)
        self.assertTrue(result.supabase_path.startswith("svc-uid/"))
        self.assertTrue(result.supabase_path.endswith(".jpg"))
        mock_storage.upload.assert_called_once()


# ---------------------------------------------------------------------------
# Service tests — get_image_url
# ---------------------------------------------------------------------------
class GetImageUrlTests(TestCase):
    @patch("users.services.get_supabase_client")
    def test_returns_signed_url(self, mock_get_client):
        from users.models import PlantImage
        from users.services import get_image_url

        user = User.objects.create_user(username="img_user", email="img@test.com")
        plant_img = PlantImage.objects.create(user=user, supabase_path="uid/img.jpg")

        mock_storage = MagicMock()
        mock_storage.create_signed_url.return_value = {
            "signedURL": "https://signed.example.com/img"
        }
        mock_get_client.return_value.storage.from_.return_value = mock_storage

        url = get_image_url(plant_img)
        self.assertEqual(url, "https://signed.example.com/img")
        mock_storage.create_signed_url.assert_called_once_with(
            path="uid/img.jpg", expires_in=3600
        )


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
