from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Admin panel
    path('admin/', admin.site.urls),
    
    # Auth endpoints 
    path('api/auth/', include('users.urls')),
    
    # add plant diagnosis API routes here later 
    # path('api/', include('api.urls')),
]
