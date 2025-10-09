from django.db import models
from django.utils import timezone
from .managers import PlantImageManager


class Dataset(models.Model):
    name = models.CharField(max_length=255, unique=True)
    source_url = models.URLField(blank=True, null=True)
    base_path = models.CharField(max_length=512)
    import_date = models.DateTimeField(default=timezone.now)
    version = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # additional metadata fields can be added as needed
    class Meta:
        ordering = ['-import_date']

    def __str__(self):
        return self.name


class PlantSpecies(models.Model):
    # again more fields can be added as needed this is a basic structure
    name = models.CharField(max_length=100, unique=True)
    scientific_name = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name_plural = "Plant species"
        ordering = ['name']

    def __str__(self):
        return self.name


class DiseaseCategory(models.Model):
    # as above
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    severity_level = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = "Disease categories"
        ordering = ['name']

    def __str__(self):
        return self.name

# basic structure of model representing images of plants with diseases
class PlantImage(models.Model):
    # these are all fields that can be changed as needed (just a skeleton for rn)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='images')
    plant_species = models.ForeignKey(PlantSpecies, on_delete=models.CASCADE, related_name='images')
    disease_category = models.ForeignKey(DiseaseCategory, on_delete=models.CASCADE, related_name='images')

    file_path = models.CharField(max_length=1024)
    image_hash = models.CharField(max_length=64, db_index=True)

    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)

    metadata_json = models.JSONField(default=dict, blank=True)

    is_validated = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = PlantImageManager()

    class Meta:
        ordering = ['dataset', 'plant_species', 'disease_category']
        indexes = [
            models.Index(fields=['image_hash']),
            models.Index(fields=['plant_species', 'disease_category']),
        ]

    def __str__(self):
        return f"{self.plant_species.name} - {self.disease_category.name}"

    @property
    def full_path(self):
        # return complete file path combining dataset base_path and file_path
        pass