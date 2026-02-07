from PIL import Image
from io import BytesIO
import uuid
from django.conf import settings
from .supabase import get_supabase_client
from .models import PlantImage, UserProfile


def create_supabase_user(email: str) -> str:
    # Creates a user in Supabase Auth.
    # Returns the Supabase UUID.
    client = get_supabase_client()
    response = client.auth.admin.create_user({
        "email": email,
        "email_confirm": True
    })
    return response.user.id
