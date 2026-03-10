from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from .serializers import PlantImageSerializer
from .services import upload_plant_image, call_inference


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
