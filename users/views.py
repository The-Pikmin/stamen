from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from .supabase import get_supabase_client
from .serializers import (
    ProfileUpdateSerializer,
    SettingsUpdateSerializer,
    serialize_scan,
    serialize_upload,
    serialize_user_profile,
)
from .services import (
    upload_plant_image,
    upload_profile_avatar,
    call_inference,
    enrich_predictions_with_common_names,
    fetch_all_diseases,
    fetch_disease,
    delete_storage_object,
    delete_profile_avatar,
    get_supabase_uid,
    get_or_create_user_profile,
    check_upload_in_use,
    EPHEMERAL_RETENTION_STATE,
    DELETING_RETENTION_STATE,
    find_upload_by_path,
    promote_upload_to_retained,
    reset_upload_to_ephemeral,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def home(request):
    return Response("Hello, this is the backend server!")


@api_view(["GET"])
@permission_classes([AllowAny])
def get_message(request):
    return Response({"message": "This is a message from the backend."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def predict(request):
    """
    Predict plant species using the Cloud Run inference service.
    Expects JSON: {"image_url": "https://<project>.supabase.co/storage/..."}
    """
    image_url = request.data.get("image_url")
    if not image_url:
        return Response(
            {"error": "image_url is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        result = call_inference(image_url)
        enrich_predictions_with_common_names(result)

        # Flag low-confidence predictions
        predictions = result.get("predictions", [])
        top_confidence = predictions[0]["confidence"] if predictions else 0
        result["low_confidence"] = top_confidence < 0.15

        return Response(result, status=status.HTTP_200_OK)
    except ValueError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Inference failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"error": "Inference service unavailable"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    user = request.user
    supabase_uid = request.auth.get("sub", "")
    profile = get_or_create_user_profile(user, supabase_uid)
    user_data = serialize_user_profile(user, profile, supabase_uid)
    return Response(user_data, status=status.HTTP_200_OK)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """Update the current user's profile fields."""
    serializer = ProfileUpdateSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(
            {"error": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    data = serializer.validated_data
    if not data:
        return Response(
            {"error": "At least one profile field is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    username = data.get("username")

    from django.contrib.auth.models import User

    if username and User.objects.filter(username=username).exclude(pk=request.user.pk).exists():
        return Response(
            {"error": "Username already taken"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = get_or_create_user_profile(request.user, request.auth.get("sub"))
    user_fields_to_update = []
    profile_fields_to_update = []

    if username:
        request.user.username = username
        user_fields_to_update.append("username")

    if "display_name" in data:
        profile.display_name = data["display_name"]
        profile_fields_to_update.extend(["display_name", "updated_at"])

    if user_fields_to_update:
        request.user.save(update_fields=user_fields_to_update)
    if profile_fields_to_update:
        profile.save(update_fields=profile_fields_to_update)

    return Response(
        serialize_user_profile(request.user, profile, request.auth.get("sub", "")),
        status=status.HTTP_200_OK,
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def user_settings(request):
    profile = get_or_create_user_profile(request.user, request.auth.get("sub"))

    if request.method == "PATCH":
        serializer = SettingsUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"error": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        fields_to_update = []

        theme = data.get("theme")
        if theme is not None:
            profile.theme_preference = theme
            fields_to_update.append("theme_preference")

        notifications = data.get("notifications", {})
        if "enabled" in notifications:
            profile.notifications_enabled = notifications["enabled"]
            fields_to_update.append("notifications_enabled")
        if "scan_reminders" in notifications:
            profile.scan_reminders_enabled = notifications["scan_reminders"]
            fields_to_update.append("scan_reminders_enabled")
        if "care_reminders" in notifications:
            profile.care_reminders_enabled = notifications["care_reminders"]
            fields_to_update.append("care_reminders_enabled")

        privacy = data.get("privacy", {})
        if "share_data" in privacy:
            profile.share_data = privacy["share_data"]
            fields_to_update.append("share_data")
        if "analytics_enabled" in privacy:
            profile.analytics_enabled = privacy["analytics_enabled"]
            fields_to_update.append("analytics_enabled")

        if fields_to_update:
            fields_to_update.append("updated_at")
            profile.save(update_fields=fields_to_update)

    return Response(
        serialize_user_profile(request.user, profile, request.auth.get("sub", ""))[
            "settings"
        ],
        status=status.HTTP_200_OK,
    )


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def user_avatar(request):
    supabase_uid = request.auth.get("sub")
    profile = get_or_create_user_profile(request.user, supabase_uid)

    if request.method == "DELETE":
        delete_profile_avatar(request.user, supabase_uid)
        return Response(status=status.HTTP_204_NO_CONTENT)

    image = request.FILES.get("image")
    if not image:
        return Response(
            {"error": "image is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload_profile_avatar(request.user, image, supabase_uid)
    profile.refresh_from_db()
    return Response(
        serialize_user_profile(request.user, profile, request.auth.get("sub", "")),
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_scan(request):
    data = request.data
    plant_name = data.get("plant_name")
    image_url = data.get("image_url")
    if not plant_name or not image_url:
        return Response(
            {"error": "plant_name and image_url are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    supabase_uid = get_supabase_uid(request)
    supabase_path = data.get("supabase_path", "")

    # Look up upload_id from plant_uploads by supabase_path
    upload_id = None
    upload_previous_retention_state = None
    if supabase_path:
        upload = find_upload_by_path(supabase_uid, supabase_path)
        if upload:
            upload_id = upload["id"]
            upload_previous_retention_state = upload.get("retention_state")
            promote_upload_to_retained(upload_id)

    # Look up disease_id from disease_static
    disease_id = None
    disease_name = data.get("disease_name", "")
    disease_genus = data.get("disease_genus", "")
    if disease_name and disease_genus:
        client = get_supabase_client()
        disease_resp = (
            client.table("disease_static")
            .select("disease_id")
            .ilike("genus", disease_genus)
            .ilike("disease_name", disease_name)
            .limit(1)
            .execute()
        )
        if disease_resp.data:
            disease_id = disease_resp.data[0]["disease_id"]

    client = get_supabase_client()
    try:
        row = (
            client.table("inferences")
            .insert(
                {
                    "user_id": supabase_uid,
                    "upload_id": upload_id,
                    "disease_id": disease_id,
                    "plant_name": plant_name,
                    "image_url": image_url,
                    "supabase_path": supabase_path,
                    "top_predictions": data.get("top_predictions", []),
                    "disease_name": disease_name,
                    "confidence": data.get("disease_confidence"),
                    "disease_genus": disease_genus,
                    "all_diseases": data.get("all_diseases", []),
                }
            )
            .execute()
        )
    except Exception:
        if upload_id and upload_previous_retention_state in (
            EPHEMERAL_RETENTION_STATE,
            DELETING_RETENTION_STATE,
        ):
            reset_upload_to_ephemeral(upload_id)
        raise

    return Response(serialize_scan(row.data[0]), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_history(request):
    supabase_uid = get_supabase_uid(request)
    client = get_supabase_client()

    response = (
        client.table("inferences")
        .select("*")
        .eq("user_id", supabase_uid)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )

    return Response(
        [serialize_scan(s) for s in response.data], status=status.HTTP_200_OK
    )


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def scan_detail(request, pk):
    supabase_uid = get_supabase_uid(request)
    client = get_supabase_client()

    response = (
        client.table("inferences")
        .select("*")
        .eq("id", pk)
        .eq("user_id", supabase_uid)
        .execute()
    )

    if not response.data:
        return Response({"error": "Scan not found"}, status=status.HTTP_404_NOT_FOUND)

    scan = response.data[0]

    if request.method == "DELETE":
        client.table("inferences").delete().eq("id", pk).execute()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(serialize_scan(scan), status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def disease_list(request):
    """List all diseases from the static_diseases table."""
    try:
        diseases = fetch_all_diseases()
        return Response(diseases, status=status.HTTP_200_OK)
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Failed to fetch diseases: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"error": "Failed to fetch diseases"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def disease_detail(request, genus, disease_name):
    """Get a single disease by genus and disease_name."""
    disease = fetch_disease(genus, disease_name)
    if not disease:
        return Response(
            {"error": "Disease not found"}, status=status.HTTP_404_NOT_FOUND
        )
    return Response(disease, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_image(request):
    if "image" not in request.FILES:
        return Response(
            {"error": "No image provided"}, status=status.HTTP_400_BAD_REQUEST
        )

    image_file = request.FILES["image"]

    try:
        row = upload_plant_image(
            user=request.user, image_file=image_file, original_filename=image_file.name
        )
        return Response(serialize_upload(row), status=status.HTTP_201_CREATED)
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Upload failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"error": "Image upload failed"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def image_list(request):
    supabase_uid = get_supabase_uid(request)
    client = get_supabase_client()

    page = int(request.query_params.get("page", 1))
    page_size = int(request.query_params.get("page_size", 24))
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    start = (page - 1) * page_size
    end = start + page_size - 1  # Supabase range is inclusive

    response = (
        client.table("plant_uploads")
        .select("*", count="exact")
        .eq("user_id", supabase_uid)
        .order("created_at", desc=True)
        .range(start, end)
        .execute()
    )

    total = response.count or 0
    results = [serialize_upload(r) for r in response.data]

    return Response(
        {
            "results": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size or 1,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def image_detail(request, pk):
    supabase_uid = get_supabase_uid(request)
    client = get_supabase_client()

    response = (
        client.table("plant_uploads")
        .select("*")
        .eq("id", pk)
        .eq("user_id", supabase_uid)
        .execute()
    )

    if not response.data:
        return Response({"error": "Upload not found"}, status=status.HTTP_404_NOT_FOUND)

    upload = response.data[0]

    if check_upload_in_use(upload["id"], supabase_uid):
        return Response(
            {
                "error": (
                    "This upload is still used by a saved scan. Delete that scan first."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )

    try:
        delete_storage_object(upload["storage_path"])
        client.table("plant_uploads").delete().eq("id", pk).execute()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Upload deletion failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"error": "Upload deletion failed"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
