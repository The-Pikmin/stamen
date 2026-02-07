from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile
from .services import create_supabase_user


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    # Automatically creates UserProfile with Supabase UUID
    # when a new Django User is created.
    if created:
        try:
            supabase_uid = create_supabase_user(email=instance.email)
            UserProfile.objects.create(
                user=instance,
                supabase_uid=supabase_uid
            )
        except Exception as e:
            print(f"Failed to create Supabase user: {e}")
            UserProfile.objects.create(user=instance)