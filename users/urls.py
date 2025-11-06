from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # User registration and login
    path('register/', views.register, name='register'),  # POST /api/auth/register/
    path('login/', views.login, name='login'),           # POST /api/auth/login/
    
    path('me/', views.get_current_user, name='current-user'),  # GET /api/auth/me/
    
    # JWT token refresh endpoint
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),  # POST /api/auth/token/refresh/
    
    # Add Google OAuth endpoints here
]
