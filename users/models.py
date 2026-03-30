from django.contrib.auth.models import User
from django.db import models

# for basic auth we dont need a custom user model yet
# but in future if needed we can extend it like this:
# from django.contrib.auth.models import AbstractUser
#
# class CustomUser(AbstractUser):
#     # Add custom fields here
#     bio = models.TextField(blank=True)
#     profile_picture = models.ImageField(upload_to='profiles/', blank=True)
#
#     def __str__(self):
#         return self.email


class UserProfile(models.Model):
    # Extends Django User to store Supabase Auth UUID
    # This UUID is used for RLS policies in Supabase
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    supabase_uid = models.CharField(max_length=36, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=80, blank=True, default="")
    avatar_path = models.CharField(max_length=255, blank=True, default="")
    theme_preference = models.CharField(max_length=10, blank=True, default="auto")
    notifications_enabled = models.BooleanField(default=True)
    scan_reminders_enabled = models.BooleanField(default=True)
    care_reminders_enabled = models.BooleanField(default=True)
    share_data = models.BooleanField(default=False)
    analytics_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} : {self.supabase_uid}"
