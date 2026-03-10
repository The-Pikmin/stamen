<div align="center">
<img width="125" height="125" src="https://emojicdn.elk.sh/🌱?style=apple"/>
<h1>Stamen - Plant Disease Diagnosis Backend</h1>
</div>

> [!NOTE]
> This is the backend application for the senior design project:
> "A07 - Computer Vision System for Plant Disease Diagnosis".

# Introduction

Stamen is a Django REST API that powers the GreenEye plant disease diagnosis app. It handles user authentication (via Supabase), image uploads to Supabase Storage, and plant species identification through a Cloud Run inference service (Lotus).

# Architecture

- **Authentication:** Supabase Auth with JWKS-based JWT verification. The frontend authenticates directly with Supabase and sends the JWT to Stamen, which verifies it against Supabase's JWKS endpoint. Django users are auto-provisioned on first request.
- **Image Storage:** Supabase Storage with EXIF stripping for privacy. Signed URLs with 1-hour expiration.
- **Inference:** Plant identification is handled by the Lotus model running on Google Cloud Run. Stamen proxies requests with Google OIDC authentication.
- **Database:** PostgreSQL (SQLite for tests).
- **Deployment:** Render with Gunicorn and WhiteNoise for static files.

# API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/` | No | Health check |
| GET | `/api/message/` | No | Test endpoint |
| GET | `/api/me/` | Yes | Get current user profile |
| PATCH | `/api/me/profile/` | Yes | Update username |
| POST | `/api/predict/` | Yes | Plant species prediction |
| POST | `/api/images/upload/` | Yes | Upload plant image |

All authenticated endpoints require a `Bearer` token (Supabase JWT) in the `Authorization` header.

# Setup

1. Install [Python](https://www.python.org/downloads/) (v3.10 or higher).

2. Clone this repository and navigate to the root directory.

3. Create and activate a virtual environment:
```bash
# Create the virtual environment
python -m venv venv

# Activate it (macOS/Linux)
source venv/bin/activate

# Activate it (Windows)
.\venv\Scripts\activate
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file in the root of the repository with the following variables:

```
SECRET_KEY=<django-secret-key>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL)
DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<database-password>
DB_HOST=localhost
DB_PORT=5432

# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<supabase-service-role-key>
SUPABASE_BUCKET=plant-images

# Cloud Run inference
CLOUD_RUN_URL=https://<lotus-service>.a.run.app
GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>
```

# Development

Run the local Django development server:
```bash
python manage.py runserver
```

Apply database migrations:
```bash
python manage.py migrate
```

# Running Tests

```bash
pytest
```

Tests use SQLite and `force_authenticate`, so no external services are needed.

# Contributing

We welcome contributions from the team! Please read our [Contributing Guide](./CONTRIBUTING.md) for the full workflow and standards.

## License

This repository is licensed under the [MIT License](./LICENSE).
