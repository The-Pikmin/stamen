from PIL import Image
from io import BytesIO
from datetime import timedelta
import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse
import requests
import google.auth.transport.requests
import google.oauth2.id_token
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from storage3.types import TransformOptions
from .models import UserProfile
from .supabase import get_supabase_client

EPHEMERAL_UPLOAD_TTL = timedelta(hours=24)
DELETING_UPLOAD_GRACE_PERIOD = timedelta(minutes=15)
EPHEMERAL_RETENTION_STATE = "ephemeral"
RETAINED_RETENTION_STATE = "retained"
DELETING_RETENTION_STATE = "deleting"

# Load common names lookup (scientific name -> common name)
_COMMON_NAMES_PATH = Path(settings.BASE_DIR) / "common_names.json"
try:
    with open(_COMMON_NAMES_PATH) as _f:
        COMMON_NAMES: dict[str, str] = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    COMMON_NAMES = {}


def enrich_predictions_with_common_names(result: dict) -> dict:
    """Add common_name field to each prediction in the inference result."""
    for pred in result.get("predictions", []):
        name = pred.get("name", "")
        pred["common_name"] = COMMON_NAMES.get(name, "")
    return result


def fetch_all_diseases() -> list[dict]:
    """Fetch all diseases from the static_diseases table."""
    client = get_supabase_client()
    response = client.table("disease_static").select("*").execute()
    return response.data


def fetch_disease(genus: str, disease_name: str) -> dict | None:
    """Fetch a single disease by genus and disease_name."""
    # DB has a mix of underscores and spaces in disease_name; try both forms.
    if "_" in disease_name:
        alt_name = disease_name.replace("_", " ")
    else:
        alt_name = disease_name.replace(" ", "_")
    client = get_supabase_client()
    response = (
        client.table("disease_static")
        .select("*")
        .ilike("genus", genus)
        .or_(f"disease_name.ilike.{disease_name},disease_name.ilike.{alt_name}")
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]
    return None


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


# strips and uploads image to supabase, returns plant_uploads row dict
def upload_plant_image(user, image_file, original_filename: str) -> dict:
    clean_image = strip_exif(image_file)
    image_bytes = clean_image.getvalue()

    supabase_uid = user.profile.supabase_uid
    unique_filename = f"{uuid.uuid4()}.jpg"
    supabase_path = f"{supabase_uid}/{unique_filename}"
    expires_at = get_ephemeral_upload_expiry()

    client = get_supabase_client()
    client.storage.from_(settings.SUPABASE_BUCKET).upload(
        path=supabase_path,
        file=image_bytes,
        file_options={"content-type": "image/jpeg"},
    )

    row = (
        client.table("plant_uploads")
        .insert(
            {
                "user_id": supabase_uid,
                "bucket": settings.SUPABASE_BUCKET,
                "storage_path": supabase_path,
                "original_name": original_filename,
                "mime_type": "image/jpeg",
                "size_bytes": len(image_bytes),
                "status": "uploaded",
                "retention_state": EPHEMERAL_RETENTION_STATE,
                "expires_at": expires_at,
            }
        )
        .execute()
    )

    return row.data[0]


def get_or_create_user_profile(user, supabase_uid: str | None = None) -> UserProfile:
    defaults = {"supabase_uid": supabase_uid} if supabase_uid else {}
    profile, _ = UserProfile.objects.get_or_create(user=user, defaults=defaults)
    if supabase_uid and profile.supabase_uid != supabase_uid:
        profile.supabase_uid = supabase_uid
        profile.save(update_fields=["supabase_uid"])
    return profile


def upload_profile_avatar(user, image_file, supabase_uid: str | None = None) -> str:
    clean_image = strip_exif(image_file)
    image_bytes = clean_image.getvalue()
    profile = get_or_create_user_profile(user, supabase_uid)
    if not profile.supabase_uid:
        raise ValueError("User profile is missing supabase_uid")

    unique_filename = f"{uuid.uuid4()}.jpg"
    supabase_path = f"avatars/{profile.supabase_uid}/{unique_filename}"

    client = get_supabase_client()
    client.storage.from_(settings.SUPABASE_BUCKET).upload(
        path=supabase_path,
        file=image_bytes,
        file_options={"content-type": "image/jpeg"},
    )

    previous_avatar_path = profile.avatar_path
    profile.avatar_path = supabase_path
    profile.save(update_fields=["avatar_path", "updated_at"])

    if previous_avatar_path:
        delete_storage_object(previous_avatar_path)

    return supabase_path


def delete_profile_avatar(user, supabase_uid: str | None = None) -> None:
    profile = get_or_create_user_profile(user, supabase_uid)
    if profile.avatar_path:
        delete_storage_object(profile.avatar_path)
        profile.avatar_path = ""
        profile.save(update_fields=["avatar_path", "updated_at"])


# Generates a signed URL for img
_SIGNED_URL_EXPIRY = 86400  # 24 hours
_THUMBNAIL_TRANSFORM: TransformOptions = {
    "width": 256,
    "height": 256,
    "resize": "cover",
    "quality": 80,
}


def _signed_url_cache_key(
    supabase_path: str, transform: TransformOptions | None = None
) -> str:
    cache_signature = json.dumps(
        {"path": supabase_path, "transform": transform or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(cache_signature.encode("utf-8")).hexdigest()
    return f"signed-url:{digest}"


def _signed_url_payload(
    supabase_path: str, transform: TransformOptions | None = None
) -> dict[str, str]:
    cache_key = _signed_url_cache_key(supabase_path, transform)
    cached_payload = cache.get(cache_key)
    if cached_payload:
        return cached_payload

    client = get_supabase_client()
    options = {"transform": transform} if transform else {}
    response = client.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
        path=supabase_path,
        expires_in=_SIGNED_URL_EXPIRY,
        options=options,
    )

    payload = {
        "url": response["signedURL"],
        "expires_at": (
            timezone.now() + timedelta(seconds=_SIGNED_URL_EXPIRY)
        ).isoformat(),
    }
    cache.set(cache_key, payload, timeout=_SIGNED_URL_EXPIRY)
    return payload


def generate_signed_url(
    supabase_path: str, transform: TransformOptions | None = None
) -> str:
    return _signed_url_payload(supabase_path, transform)["url"]


def get_signed_image_urls(supabase_path: str) -> dict[str, str]:
    full_size = _signed_url_payload(supabase_path)
    thumbnail = _signed_url_payload(supabase_path, _THUMBNAIL_TRANSFORM)

    return {
        "url": full_size["url"],
        "thumbnail_url": thumbnail["url"],
        "expires_at": min(full_size["expires_at"], thumbnail["expires_at"]),
    }


def get_image_url(supabase_path: str) -> str:
    return _signed_url_payload(supabase_path)["url"]


def get_ephemeral_upload_expiry() -> str:
    return (timezone.now() + EPHEMERAL_UPLOAD_TTL).isoformat()


def get_deleting_upload_expiry() -> str:
    return (timezone.now() + DELETING_UPLOAD_GRACE_PERIOD).isoformat()


def promote_upload_to_retained(upload_id: str) -> bool:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .update(
            {
                "retention_state": RETAINED_RETENTION_STATE,
                "expires_at": None,
                "retained_at": timezone.now().isoformat(),
            }
        )
        .eq("id", upload_id)
        .execute()
    )
    return bool(response.data)


def find_upload_by_path(user_id: str, supabase_path: str) -> dict | None:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .select("id, retention_state, expires_at")
        .eq("user_id", user_id)
        .eq("storage_path", supabase_path)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]
    return None


def claim_expired_uploads(limit: int) -> list[dict]:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .select("id, storage_path, user_id, expires_at, retention_state")
        .eq("retention_state", EPHEMERAL_RETENTION_STATE)
        .lte("expires_at", timezone.now().isoformat())
        .limit(limit)
        .execute()
    )
    return response.data


def get_uploads_ready_for_cleanup(limit: int) -> list[dict]:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .select("id, storage_path, user_id, expires_at, retention_state")
        .eq("retention_state", DELETING_RETENTION_STATE)
        .lte("expires_at", timezone.now().isoformat())
        .limit(limit)
        .execute()
    )
    return response.data


def mark_upload_as_deleting(upload_id: str) -> bool:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .update(
            {
                "retention_state": DELETING_RETENTION_STATE,
                "expires_at": get_deleting_upload_expiry(),
            }
        )
        .eq("id", upload_id)
        .eq("retention_state", EPHEMERAL_RETENTION_STATE)
        .execute()
    )
    return bool(response.data)


def upload_is_still_deleting(upload_id: str) -> bool:
    client = get_supabase_client()
    response = (
        client.table("plant_uploads")
        .select("id")
        .eq("id", upload_id)
        .eq("retention_state", DELETING_RETENTION_STATE)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def reset_upload_to_ephemeral(upload_id: str) -> None:
    client = get_supabase_client()
    client.table("plant_uploads").update(
        {
            "retention_state": EPHEMERAL_RETENTION_STATE,
            "expires_at": get_ephemeral_upload_expiry(),
        }
    ).eq("id", upload_id).execute()


def delete_upload_record(upload_id: str) -> None:
    client = get_supabase_client()
    client.table("plant_uploads").delete().eq("id", upload_id).execute()


def delete_storage_object(supabase_path: str) -> None:
    client = get_supabase_client()
    client.storage.from_(settings.SUPABASE_BUCKET).remove([supabase_path])


def get_supabase_uid(request) -> str:
    """Extract the supabase_uid from the authenticated user's profile."""
    return request.user.profile.supabase_uid


def check_upload_in_use(upload_id: str, user_id: str) -> bool:
    """Check if any inference owned by this user references this upload."""
    client = get_supabase_client()
    response = (
        client.table("inferences")
        .select("id")
        .eq("upload_id", upload_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return len(response.data) > 0


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
        timeout=300,
    )
    response.raise_for_status()
    return response.json()
