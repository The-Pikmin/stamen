from django.contrib.auth.models import User

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
