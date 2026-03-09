from django.contrib.auth.models import User
from django.db import models

# for basic auth we dont need a custom user model yet but in future if needed we can extend it like this:
# from django.contrib.auth.models import AbstractUser
#
# class CustomUser(AbstractUser):
#     # Add custom fields here
#     bio = models.TextField(blank=True)
#     profile_picture = models.ImageField(upload_to='profiles/', blank=True)
#
#     def __str__(self):
#         return self.email


class PlantImage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    supabase_path = models.CharField(max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class UserProfile(models.Model):
    # Extends Django User to store Supabase Auth UUID
    # This UUID is used for RLS policies in Supabase
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    supabase_uid = models.CharField(max_length=36, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} : {self.supabase_uid}"
