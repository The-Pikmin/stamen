from django.db import models


class PlantImageQuerySet(models.QuerySet):

    def for_disease(self, disease_name):
        # filter images by disease category name
        pass

    def for_species(self, species_name):
        # filter images by plant species name
        pass

    def for_dataset(self, dataset_name):
        # filter images by dataset name
        pass

    def validated_only(self):
        # return only validated images
        pass

    def exclude_duplicates(self):
        # exclude images marked as duplicates
        pass

    # these are both based on stratified sampling
    def training_split(self, ratio=0.8, random_state=42):
        # return stratified training split
        pass

    def validation_split(self, ratio=0.2, random_state=42):
        # return stratified validation split
        pass


class PlantImageManager(models.Manager):

    def get_queryset(self):
        return PlantImageQuerySet(self.model, using=self._db)

    def for_disease(self, disease_name):
        return self.get_queryset().for_disease(disease_name)

    def for_species(self, species_name):
        return self.get_queryset().for_species(species_name)

    def for_dataset(self, dataset_name):
        return self.get_queryset().for_dataset(dataset_name)

    def validated_only(self):
        return self.get_queryset().validated_only()

    def exclude_duplicates(self):
        return self.get_queryset().exclude_duplicates()