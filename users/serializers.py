from rest_framework import serializers
from .models import UserProfile
from .services import get_image_url, get_signed_image_urls, check_upload_in_use


class NotificationSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    scan_reminders = serializers.BooleanField(required=False)
    care_reminders = serializers.BooleanField(required=False)


class PrivacySettingsSerializer(serializers.Serializer):
    share_data = serializers.BooleanField(required=False)
    analytics_enabled = serializers.BooleanField(required=False)


class ProfileUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, min_length=2, max_length=150)
    display_name = serializers.CharField(
        required=False, allow_blank=True, max_length=80
    )


class SettingsUpdateSerializer(serializers.Serializer):
    theme = serializers.ChoiceField(
        required=False,
        choices=["light", "dark", "auto"],
    )
    notifications = NotificationSettingsSerializer(required=False)
    privacy = PrivacySettingsSerializer(required=False)


def serialize_user_profile(user, profile: UserProfile, supabase_uid: str) -> dict:
    avatar_url = get_image_url(profile.avatar_path) if profile.avatar_path else ""
    return {
        "id": supabase_uid,
        "username": user.username,
        "email": user.email,
        "display_name": profile.display_name or user.username,
        "avatar_url": avatar_url,
        "joined_at": profile.created_at.isoformat(),
        "settings": {
            "theme": profile.theme_preference,
            "notifications": {
                "enabled": profile.notifications_enabled,
                "scan_reminders": profile.scan_reminders_enabled,
                "care_reminders": profile.care_reminders_enabled,
            },
            "privacy": {
                "share_data": profile.share_data,
                "analytics_enabled": profile.analytics_enabled,
            },
        },
    }


def serialize_upload(row: dict) -> dict:
    """Build API response dict from a plant_uploads Supabase row."""
    signed_urls = get_signed_image_urls(row["storage_path"])
    return {
        "id": row["id"],
        "supabase_path": row["storage_path"],
        "uploaded_at": row["created_at"],
        "url": signed_urls["url"],
        "thumbnail_url": signed_urls["thumbnail_url"],
        "url_expires_at": signed_urls["expires_at"],
        "in_use": check_upload_in_use(row["id"], row["user_id"]),
    }


def serialize_scan(row: dict) -> dict:
    """Build API response dict from an inferences Supabase row."""
    image_url = row.get("image_url", "")
    thumbnail_url = image_url
    image_url_expires_at = ""
    supabase_path = row.get("supabase_path", "")
    if supabase_path:
        signed_urls = get_signed_image_urls(supabase_path)
        image_url = signed_urls["url"]
        thumbnail_url = signed_urls["thumbnail_url"]
        image_url_expires_at = signed_urls["expires_at"]

    return {
        "id": row["id"],
        "image_url": image_url,
        "thumbnail_url": thumbnail_url,
        "image_url_expires_at": image_url_expires_at,
        "plant_name": row.get("plant_name", ""),
        "top_predictions": row.get("top_predictions", []),
        "disease_name": row.get("disease_name", ""),
        "disease_confidence": row.get("confidence"),
        "disease_genus": row.get("disease_genus", ""),
        "all_diseases": row.get("all_diseases", []),
        "created_at": row.get("created_at", ""),
    }
