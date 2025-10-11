from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count

from .models import Dataset, PlantSpecies, DiseaseCategory, PlantImage
from .serializers import (
    DatasetSerializer, PlantSpeciesSerializer,
    DiseaseCategorySerializer, PlantImageSerializer,
    PlantImageListSerializer, TrainingDataSerializer
)


# since we dont wanna change the info we are using readonly viewsets
class DatasetViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dataset.objects.all().annotate(image_count=Count('images'))
    serializer_class = DatasetSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'source_url']
    ordering_fields = ['name', 'import_date']
    ordering = ['-import_date']

    # get statistics for a specific dataset
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        # get dataset
        # count total images
        # count by species
        # count by disease
        # return structured statistics
        pass

    # get summary statistics across all datasets
    @action(detail=False, methods=['get'])
    def summary(self, request):
        # total datasets
        # total images
        # top species
        # top diseases
        # return structured summary
        pass

class PlantSpeciesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PlantSpecies.objects.all().annotate(image_count=Count('images'))
    serializer_class = PlantSpeciesSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'scientific_name']
    ordering_fields = ['name']
    ordering = ['name']

    # get diseases associated with this plant species
    @action(detail=True, methods=['get'])
    def diseases(self, request, pk=None):
        # get species
        # aggregate diseases from images
        # return list of diseases with counts
        pass

    # get images for this plant species
    @action(detail=True, methods=['get'])
    def images(self, request, pk=None):
        # filter images by species
        # paginate and serialize
        pass

class DiseaseCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DiseaseCategory.objects.all().annotate(image_count=Count('images'))
    serializer_class = DiseaseCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'severity_level']
    ordering = ['name']

    # get all images for this disease across all datasets
    @action(detail=True, methods=['get'])
    def images(self, request, pk=None):
        # get disease
        # return paginated list of images
        # optionally filter by species or dataset via query params
        pass

    # get image counts for this disease broken down by dataset
    @action(detail=True, methods=['get'])
    def by_dataset(self, request, pk=None):
        # get disease
        # count images per dataset
        # return structured breakdown
        pass


class PlantImageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PlantImage.objects.select_related('dataset', 'plant_species', 'disease_category')
    serializer_class = PlantImageSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'dataset': ['exact'],
        'plant_species': ['exact'],
        'disease_category': ['exact'],
        'is_validated': ['exact'],
        'is_duplicate': ['exact'],
    }
    search_fields = ['plant_species__name', 'disease_category__name', 'file_path']
    ordering_fields = ['created_at', 'plant_species__name', 'disease_category__name']
    ordering = ['-created_at']

    # use lighter serializer for list view
    def get_serializer_class(self):
        # if action is list, return PlantImageListSerializer
        # otherwise return PlantImageSerializer
        pass

    # query images by disease name
    @action(detail=False, methods=['get'])
    def by_disease(self, request):
        # get disease name from query params
        # filter images
        # return paginated results
        pass

    # query images by species name
    @action(detail=False, methods=['get'])
    def by_species(self, request):
        # get species name from query params
        # filter images
        # return paginated results
        pass

    @action(detail=False, methods=['post'])
    def training_split(self, request):
        """
        get train/validation split for training
        POST body: {
            "species": "tomato",
            "disease": "early_blight",
            "train_split": 0.8,
            "exclude_duplicates": true,
            "validated_only": false
        }
        """

        # validate input with TrainingDataSerializer
        # build queryset based on filters
        # split into train/val
        # return file paths for both sets
        pass

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        # total images
        # validated vs unvalidated
        # duplicates count
        # images per species
        # images per disease
        pass

#simple health check endpoint
class HealthCheckViewSet(viewsets.ViewSet):
    def list(self, request):
        # return basic health status
        # database connection ok
        # data directory accessible
        pass