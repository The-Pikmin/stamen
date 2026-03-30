<div align="center">
<img width="125" height="125" src="https://emojicdn.elk.sh/🌱?style=apple"/>
<h1>Stamen - Plant Disease Diagnosis Backend</h1>
</div>

> [!NOTE]
> This is the backend application for the senior design project:
> "A07 - Computer Vision System for Plant Disease Diagnosis".

# Introduction

Stamen is the Django REST API behind GreenEye. It handles Supabase-authenticated users, image upload and retention in Supabase Storage, plant species identification through Lotus on Cloud Run, scan history management, disease-library lookups, and persisted profile/settings data for the frontend.

# Architecture

- **Authentication:** Supabase Auth with JWKS-based JWT verification. The frontend authenticates directly with Supabase and sends the JWT to Stamen, which verifies it against Supabase's JWKS endpoint. Django users are auto-provisioned on first request.
- **Image Storage:** Supabase Storage with EXIF stripping for privacy. Signed URLs are cached for their 24-hour validity window, and list views use transformed thumbnail URLs.
- **Inference:** Plant identification is handled by the Lotus model running on Google Cloud Run. Stamen proxies requests with Google OIDC authentication. Predictions are enriched with common names from a static lookup before returning to the frontend. Low-confidence results (top prediction < 15%) are flagged.
- **Disease Library:** Treatment and prevention information is stored in a Supabase `disease_static` table and served via dedicated endpoints.
- **Scan History:** Users can save scan results and retrieve them later. Scans store the image URL, plant name, top predictions (as JSON), and disease analysis.
- **Profile & Settings:** User profiles persist display name, avatar, theme preference, notification preferences, and privacy settings.
- **Upload Retention:** Newly uploaded scan images start as ephemeral uploads and are cleaned up by a scheduled job unless the user saves the scan to history.
- **Database:** PostgreSQL (SQLite for tests).
- **Deployment:** Render with Gunicorn and WhiteNoise for static files. The Render build step runs Django migrations automatically via `build.sh`.

# API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/` | No | Health check |
| GET | `/api/message/` | No | Test endpoint |
| GET | `/api/me/` | Yes | Get the current user's full profile and persisted settings |
| PATCH | `/api/me/profile/` | Yes | Update username and display name |
| GET/PATCH | `/api/me/settings/` | Yes | Read or update theme, notification, and privacy settings |
| POST/DELETE | `/api/me/avatar/` | Yes | Upload or remove a profile photo |
| POST | `/api/predict/` | Yes | Plant species + disease prediction (returns `low_confidence` flag) |
| POST | `/api/images/upload/` | Yes | Upload plant image to Supabase Storage |
| POST | `/api/scans/` | Yes | Save a scan result to history |
| GET | `/api/scans/list/` | Yes | Get scan history (most recent 50) |
| GET | `/api/scans/<id>/` | Yes | Get a single scan by ID |
| GET | `/api/diseases/` | Yes | List all diseases from the library |
| GET | `/api/diseases/<genus>/<disease_name>/` | Yes | Get disease details with treatment info |

All authenticated endpoints require a `Bearer` token (Supabase JWT) in the `Authorization` header.

# Setup

1. Install [Python](https://www.python.org/downloads/) (`3.12` recommended; see [`.python-version`](./.python-version)).

2. Clone this repository and navigate to the `stamen/` directory.

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

Create a `.env` file in the `stamen/` directory with the following variables:

```
SECRET_KEY=<django-secret-key>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (preferred)
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database-name>

# Or individual DB_* settings
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

# CORS for production deployments
CORS_ALLOWED_ORIGINS=https://<petal-domain>
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

Render production deploys already run `python manage.py migrate` as part of [`build.sh`](./build.sh).

# Running Tests

```bash
pytest
```

Tests use SQLite and `force_authenticate`, so no external services are needed.

## Notable Current Behavior

- Saved scan history uses cached signed URLs and thumbnail URLs to reduce repeated Supabase work.
- Unsaved uploads are retained temporarily for retry safety, then cleaned up by `python manage.py cleanup_ephemeral_uploads`.
- Profile photos are stored in the same Supabase bucket as scan uploads, under an `avatars/` prefix.

# Contributing

We welcome contributions from the team! Please read our [Contributing Guide](./CONTRIBUTING.md) for the full workflow and standards.

## License

This repository is licensed under the [MIT License](./LICENSE).
