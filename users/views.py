from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from .models import PlantImage, ScanResult
from .serializers import PlantImageSerializer, ScanResultSerializer
from .services import (
    upload_plant_image,
    call_inference,
    enrich_predictions_with_common_names,
    fetch_all_diseases,
    fetch_disease,
    delete_storage_object,
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
    user_data = {
        "id": request.auth.get("sub"),
        "username": user.username,
        "email": user.email,
    }
    return Response(user_data, status=status.HTTP_200_OK)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """Update the current user's profile (e.g. username)."""
    username = request.data.get("username")
    if not username:
        return Response(
            {"error": "username is required"}, status=status.HTTP_400_BAD_REQUEST
        )

    from django.contrib.auth.models import User

    if User.objects.filter(username=username).exclude(pk=request.user.pk).exists():
        return Response(
            {"error": "Username already taken"}, status=status.HTTP_400_BAD_REQUEST
        )

    request.user.username = username
    request.user.save(update_fields=["username"])

    return Response(
        {
            "id": request.auth.get("sub"),
            "username": request.user.username,
            "email": request.user.email,
        },
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

    scan = ScanResult.objects.create(
        user=request.user,
        image_url=image_url,
        supabase_path=data.get("supabase_path", ""),
        plant_name=plant_name,
        top_predictions=data.get("top_predictions", []),
        disease_name=data.get("disease_name", ""),
        disease_confidence=data.get("disease_confidence"),
        disease_genus=data.get("disease_genus", ""),
        all_diseases=data.get("all_diseases", []),
    )
    serializer = ScanResultSerializer(scan)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_history(request):
    scans = ScanResult.objects.filter(user=request.user)[:50]
    serializer = ScanResultSerializer(scans, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def scan_detail(request, pk):
    try:
        scan = ScanResult.objects.get(pk=pk, user=request.user)
    except ScanResult.DoesNotExist:
        return Response({"error": "Scan not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        scan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = ScanResultSerializer(scan)
    return Response(serializer.data, status=status.HTTP_200_OK)


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
        plant_image = upload_plant_image(
            user=request.user, image_file=image_file, original_filename=image_file.name
        )
        serializer = PlantImageSerializer(plant_image)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
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
    images = PlantImage.objects.filter(user=request.user).order_by("-uploaded_at")
    serializer = PlantImageSerializer(images, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def image_detail(request, pk):
    try:
        image = PlantImage.objects.get(pk=pk, user=request.user)
    except PlantImage.DoesNotExist:
        return Response({"error": "Upload not found"}, status=status.HTTP_404_NOT_FOUND)

    is_in_use = ScanResult.objects.filter(
        user=request.user, supabase_path=image.supabase_path
    ).exists()
    if is_in_use:
        return Response(
            {
                "error": "This upload is still used by a saved scan. Delete that scan first."
            },
            status=status.HTTP_409_CONFLICT,
        )

    try:
        delete_storage_object(image.supabase_path)
        image.delete()
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
