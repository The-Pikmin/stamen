# provides a base class for dataset importers with common methods and structure
from abc import ABC, abstractmethod

# helps image processing (since we wanna keep track of duplicates etc)
class BaseDatasetImporter(ABC):
    def __init__(self, dataset_name, base_path):
        self.dataset_name = dataset_name
        self.base_path = base_path
        self.stats = {
            'processed': 0,
            'imported': 0,
            'duplicates': 0,
            'errors': 0
        }

    @abstractmethod
    def parse_directory_structure(self):
        # scan directory and identify images with metadata
        pass

    @abstractmethod
    def extract_metadata(self, file_path):
        # extract species, disease, and other metadata from file/folder names
        pass

    def validate_image(self, file_path):
        # check if image is valid, not corrupted, meets size requirements
        pass

    def calculate_hash(self, file_path):
        # calculate perceptual hash for deduplication
        pass

    def get_or_create_species(self, species_name):
        # get or create plant species in database
        pass

    def get_or_create_disease(self, disease_name):
        # get or create disease category in database
        pass

    def check_duplicate(self, image_hash):
        # check if image with this hash already exists
        pass

    def import_image(self, file_path, metadata):
        # create plantimage record in database
        pass

    def run(self):
        # main import logic orchestrating all methods
        pass

    def print_stats(self):
        # print import statistics
        pass