"""
End-to-end tests for the predict flow.
Mocks Cloud Run so you can test locally without credentials.

Run with: python manage.py test users
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from users.services import validate_supabase_url


MOCK_CLOUD_RUN_URL = "https://lotus-model-test-uc.a.run.app"

MOCK_PREDICTIONS = {
    "predictions": [
        {"species_id": "1362954", "name": "Schefflera actinophylla", "confidence": 0.8732},
        {"species_id": "1363004", "name": "Heptapleurum arboricola", "confidence": 0.0521},
        {"species_id": "1361853", "name": "Fatsia japonica", "confidence": 0.0198},
        {"species_id": "1362001", "name": "Tetrapanax papyrifer", "confidence": 0.0112},
        {"species_id": "1363901", "name": "Polyscias fruticosa", "confidence": 0.0087},
    ]
}

VALID_IMAGE_URL = "https://myproject.supabase.co/storage/v1/object/public/plants/img.jpg"
VALID_SIGNED_URL = "https://myproject.supabase.co/storage/v1/object/sign/plants/img.jpg?token=abc123"


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
            validate_supabase_url("http://myproject.supabase.co/storage/v1/object/public/plants/img.jpg")
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
        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("users.services.requests.post")
    @patch("users.services._get_id_token", return_value="mock-token")
    def test_predict_with_valid_image_url(self, mock_token, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_PREDICTIONS
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("predictions", resp.json())
        self.assertEqual(len(resp.json()["predictions"]), 5)

        # Verify Cloud Run was called with correct auth
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.kwargs["headers"]["Authorization"], "Bearer mock-token")

    def test_predict_rejects_non_supabase_url(self):
        resp = self.client.post("/api/predict/", {"image_url": "https://evil.com/malicious.jpg"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supabase.co", resp.json()["error"])

    def test_predict_rejects_http_url(self):
        resp = self.client.post("/api/predict/", {"image_url": "http://myproject.supabase.co/img.jpg"}, format="json")
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
        mock_post.return_value.raise_for_status.side_effect = req_lib.HTTPError("Cloud Run error")

        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")
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

        resp = self.client.post("/api/predict/", {"image_url": VALID_SIGNED_URL}, format="json")
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

        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")
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

        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")
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
        resp = self.client.post("/api/predict/", {"image_url": VALID_IMAGE_URL}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("CLOUD_RUN_URL", resp.json()["error"])
