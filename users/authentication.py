import jwt
from jwt import PyJWKClient
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import UserProfile

_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300)
    return _jwks_client


class SupabaseJWTAuthentication(BaseAuthentication):
    """
    Authenticates requests using Supabase JWTs.
    Extracts the Bearer token, verifies it against Supabase's JWKS endpoint,
    and returns the linked Django user (auto-provisioning if needed).
    """

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]

        if not settings.SUPABASE_URL:
            raise AuthenticationFailed('SUPABASE_URL is not configured')

        try:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=['RS256', 'ES256'],
                audience='authenticated',
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token has expired')
        except jwt.InvalidTokenError:
            raise AuthenticationFailed('Invalid token')

        supabase_uid = payload.get('sub')
        if not supabase_uid:
            raise AuthenticationFailed('Token missing sub claim')

        email = payload.get('email', '')
        user_metadata = payload.get('user_metadata', {})

        user = self._get_or_create_user(supabase_uid, email, user_metadata)
        return (user, payload)

    def _get_or_create_user(self, supabase_uid, email, user_metadata):
        try:
            profile = UserProfile.objects.select_related('user').get(
                supabase_uid=supabase_uid
            )
            return profile.user
        except UserProfile.DoesNotExist:
            pass

        # Auto-provision: derive username from metadata or email
        username = (
            user_metadata.get('username')
            or user_metadata.get('full_name', '').replace(' ', '_').lower()
            or email.split('@')[0]
            or supabase_uid[:8]
        )

        # Ensure username uniqueness
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base_username}_{counter}'
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
        )
        user.set_unusable_password()
        user.save()

        UserProfile.objects.create(user=user, supabase_uid=supabase_uid)
        return user
