from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'datasets', views.DatasetViewSet, basename='dataset')
router.register(r'species', views.PlantSpeciesViewSet, basename='species')
router.register(r'diseases', views.DiseaseCategoryViewSet, basename='disease')
router.register(r'images', views.PlantImageViewSet, basename='image')

app_name = 'datasets'

urlpatterns = [
    path('', include(router.urls)),
]