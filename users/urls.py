from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    home,
    get_message,
    predict,
    register,
    login,
    get_current_user,
    upload_image,
    # Add these once created in views
    # list_images,
    # image_detail,
)

urlpatterns = [
    # old flask routes migrated to django
    path('', home, name='home'),
    path('message/', get_message, name='get_message'),
    path('predict/', predict, name='predict'),

    # User registration and login
    path('register/', register, name='register'),
    path('login/', login, name='login'),
    path('me/', get_current_user, name='current-user'),
    
    # JWT token refresh endpoint
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    
    path('images/upload/', upload_image, name='upload_image'),

    # Image routes (uncomment once views are created)
    # path('images/', list_images, name='list_images'),
    # path('images/<int:image_id>/', image_detail, name='image_detail'),
]