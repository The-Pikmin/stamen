from rest_framework import serializers
from django.contrib.auth.models import User
from .models import PlantImage

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class PlantImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = PlantImage
        fields = ['id', 'supabase_path', 'uploaded_at', 'url']
        read_only_fields = ['id', 'supabase_path', 'uploaded_at', 'url']

    def get_url(self, obj):
        from .services import get_image_url
        return get_image_url(obj)

