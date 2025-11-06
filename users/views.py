from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .serializers import UserSerializer, RegisterSerializer

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
