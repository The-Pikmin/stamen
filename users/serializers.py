from rest_framework import serializers
from django.contrib.auth.models import User
from .services import generate_signed_url, check_upload_in_use


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


def serialize_upload(row: dict) -> dict:
    """Build API response dict from a plant_uploads Supabase row."""
    return {
        "id": row["id"],
        "supabase_path": row["storage_path"],
        "uploaded_at": row["created_at"],
        "url": generate_signed_url(row["storage_path"]),
        "in_use": check_upload_in_use(row["id"], row["user_id"]),
    }


def serialize_scan(row: dict) -> dict:
    """Build API response dict from an inferences Supabase row."""
    image_url = row.get("image_url", "")
    supabase_path = row.get("supabase_path", "")
    if supabase_path:
        image_url = generate_signed_url(supabase_path)

    return {
        "id": row["id"],
        "image_url": image_url,
        "plant_name": row.get("plant_name", ""),
        "top_predictions": row.get("top_predictions", []),
        "disease_name": row.get("disease_name", ""),
        "disease_confidence": row.get("confidence"),
        "disease_genus": row.get("disease_genus", ""),
        "all_diseases": row.get("all_diseases", []),
        "created_at": row.get("created_at", ""),
    }
