from PIL import Image
from io import BytesIO
import uuid
from urllib.parse import urlparse
import requests
import google.auth.transport.requests
import google.oauth2.id_token
from django.conf import settings
from .supabase import get_supabase_client
from .models import PlantImage


# Removes all EXIF metadata (including GPS location) from img
def strip_exif(image_file) -> BytesIO:
    img = Image.open(image_file)
    data = BytesIO()

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(data, format="JPEG", quality=90)
    data.seek(0)
    return data


# Validates that the URL is a Supabase storage URL
def validate_supabase_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Image URL must use HTTPS")
    if not parsed.hostname or not parsed.hostname.endswith(".supabase.co"):
        raise ValueError("Image URL must be a *.supabase.co domain")


# strips and uploads image to supabase
def upload_plant_image(user, image_file, original_filename: str) -> PlantImage:
    clean_image = strip_exif(image_file)

    supabase_uid = user.profile.supabase_uid
    unique_filename = f"{uuid.uuid4()}.jpg"
    supabase_path = f"{supabase_uid}/{unique_filename}"

    client = get_supabase_client()
    client.storage.from_(settings.SUPABASE_BUCKET).upload(
        path=supabase_path,
        file=clean_image.getvalue(),
        file_options={"content-type": "image/jpeg"},
    )

    plant_image = PlantImage.objects.create(user=user, supabase_path=supabase_path)

    return plant_image


# Generates a signed URL for img
def get_image_url(plant_image: PlantImage) -> str:
    client = get_supabase_client()
    response = client.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
        path=plant_image.supabase_path,
        expires_in=3600,  # 1 hour expiration (security measure)
    )
    return response["signedURL"]


def _get_id_token(audience: str) -> str:
    # Fetches a Google OIDC identity token
    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


def call_inference(image_url: str) -> dict:
    # Calls Lotus inference on Cloud Run
    # Validates the URL before sending, then returns top-5 predictions
    if not settings.CLOUD_RUN_URL:
        raise ValueError("CLOUD_RUN_URL is not configured in settings")

    # Validate URL before sending to Cloud Run
    validate_supabase_url(image_url)

    # Get OIDC token for authenticating with Cloud Run
    token = _get_id_token(settings.CLOUD_RUN_URL)

    # Call the Cloud Run inference endpoint
    response = requests.post(
        f"{settings.CLOUD_RUN_URL}/predict",
        json={"image_url": image_url},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
