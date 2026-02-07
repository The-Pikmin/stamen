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

# Removes all EXIF metadata (including GPS location) from img
def strip_exif(image_file) -> BytesIO:
    img = Image.open(image_file)
    data = BytesIO()
    
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    img.save(data, format='JPEG', quality=90)
    data.seek(0)
    return data

# strips and uploads image to supabase
def upload_plant_image(user, image_file, original_filename: str) -> PlantImage:
    clean_image = strip_exif(image_file)
    
    supabase_uid = user.profile.supabase_uid
    unique_filename = f"{uuid.uuid4()}.jpg"
    supabase_path = f"{supabase_uid}/{unique_filename}"
    
    client = get_supabase_client()
    client.storage.from_(settings.SUPABASE_BUCKET).upload(
        path=supabase_path,
        file=clean_image.getvalue(),
        file_options={"content-type": "image/jpeg"}
    )
    
    plant_image = PlantImage.objects.create(
        user=user,
        supabase_path=supabase_path
    )
    
    return plant_image

# Generates a signed URL for img
def get_image_url(plant_image: PlantImage) -> str:
    client = get_supabase_client()
    response = client.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
        path=plant_image.supabase_path,
        expires_in=3600 # 1 hour expiration (security measure)
    )
    return response['signedURL']