from supabase import create_client, Client
from django.conf import settings


def get_supabase_client() -> Client:
    # Returns an authenticated Supabase client instance
    # Uses the service role key for server-side ops
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise ValueError("Supabase credentials not configured")
    
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)