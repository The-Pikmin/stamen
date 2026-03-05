from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.conf import settings
from .serializers import UserSerializer, RegisterSerializer
from .models import PlantImage
from .serializers import UserSerializer, RegisterSerializer, PlantImageSerializer
from .services import upload_plant_image, get_image_url, call_inference
# import cv2  # image handling
# import numpy as np  # array / numerical operations
# import tensorflow as tf  # ML model handling
# import json
# import os

# Local model loading (commented out - now using Cloud Run)
# Load the trained model (I have copied model.keras into the same directory as the stamen branch for testing)
# MODEL_PATH = os.path.join(settings.BASE_DIR, "model.keras")
# model = tf.keras.models.load_model(MODEL_PATH)

# Define class names that the model will be able to return, I have just copied the base metadata file for testing
# Load class names
# CLASS_NAMES_PATH = os.path.join(settings.BASE_DIR, "class_names.json")
# with open(CLASS_NAMES_PATH, "r") as f:
#     class_names = json.load(f)


@api_view(['GET'])
@permission_classes([AllowAny])
def home(request):
    return Response("Hello, this is the backend server!")


@api_view(['GET'])
@permission_classes([AllowAny])
def get_message(request):
    # message = {"message": "This is a message from the backend."}
    return Response({"message": "This is a message from the backend."})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def predict(request):
    """
    Predict plant species using the Cloud Run inference service.
    Expects JSON: {"image_url": "https://<project>.supabase.co/storage/..."}
    """
    image_url = request.data.get('image_url')
    if not image_url:
        return Response(
            {"error": "image_url is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        result = call_inference(image_url)
        return Response(result, status=status.HTTP_200_OK)
    except ValueError as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Inference failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response(
            {"error": "Inference service unavailable"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
# Expected JSON:
# {
#     "username": "john_doe",
#     "email": "john@example.com",
#     "password": "securepassword123"
# }

@api_view(['POST'])
@permission_classes([AllowAny])  # Anyone can register
def register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        username = serializer.validated_data['username']
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            return Response({"error": "Username or email already exists."}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create_user(username=username, email=email, password=password)
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# Expected JSON:
# {
#     "username": "john_doe",
#     "password": "password123"
# }
@api_view(['POST'])
@permission_classes([AllowAny])  # Anyone can login
def login(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(request, username=username, password=password)
    if user is not None:
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)


# Get current user's profile info
@api_view(['GET'])
@permission_classes([IsAuthenticated])  # Must be logged in
def get_current_user(request):
    user = request.user
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }
    return Response(user_data, status=status.HTTP_200_OK)


# Helper function to generate tokens
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_image(request):
    # Upload a plant image. EXIF data is stripped automatically.
    if 'image' not in request.FILES:
        return Response(
            {"error": "No image provided"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    image_file = request.FILES['image']
    
    try:
        plant_image = upload_plant_image(
            user=request.user,
            image_file=image_file,
            original_filename=image_file.name
        )
        serializer = PlantImageSerializer(plant_image)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    except Exception as e:
        if settings.DEBUG:
            return Response(
                {"error": f"Upload failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response(
            {"error": "Image upload failed"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
