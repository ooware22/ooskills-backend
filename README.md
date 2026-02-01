# OOSkills Backend API

A Django REST Framework backend for the OOSkills online learning platform. This API powers the landing page CMS, user authentication, and administrative features.

## 🚀 Features

- **JWT Authentication** - Secure token-based authentication with refresh tokens
- **Multi-language CMS** - Landing page content management with FR/EN/AR support
- **User Management** - Registration, profiles, referral system
- **Admin Dashboard API** - Full CRUD operations for content management
- **Supabase Integration** - Cloud database synchronization
- **Caching** - Database caching for optimized public API responses

---

## 📋 Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running the Server](#running-the-server)
- [API Endpoints](#api-endpoints)
- [Sample API Requests](#sample-api-requests)
- [Project Structure](#project-structure)

---

## Requirements

- Python 3.10+
- PostgreSQL (or SQLite for development)
- pip

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ooware22/ooskills-backend.git
cd ooskills-backend/ooskillsbackend
```

### 2. Create virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

Create a `.env` file in the `ooskillsbackend/` directory:

```env
# Django
SECRET_KEY=your-super-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL)
DATABASE_URL=postgres://user:password@localhost:5432/ooskills

# Supabase (optional)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_KEY=your-supabase-service-key

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### 5. Run migrations

```bash
python manage.py migrate
python manage.py createcachetable
```

### 6. Create superuser

```bash
python manage.py createsuperuser
```

---

## Running the Server

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/`

---

## API Endpoints

### 🔐 Authentication (`/api/auth/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register new user |
| POST | `/api/auth/login/` | Login (obtain JWT tokens) |
| POST | `/api/auth/token/refresh/` | Refresh access token |
| POST | `/api/auth/token/verify/` | Verify token validity |
| GET | `/api/auth/me/` | Get current user profile |
| PUT/PATCH | `/api/auth/me/` | Update user profile |
| POST | `/api/auth/change-password/` | Change password |
| POST | `/api/auth/logout/` | Logout (blacklist token) |
| GET | `/api/auth/my-referral-code/` | Get user's referral code |
| GET | `/api/auth/my-referrals/` | List referred users |

### 🌐 Public Landing Page (`/api/public/landing/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/public/landing/` | Full landing page data |
| GET | `/api/public/landing/?lang=fr` | Landing page (French) |
| GET | `/api/public/landing/?lang=ar` | Landing page (Arabic) |
| GET | `/api/public/landing/?lang=en` | Landing page (English) |
| GET | `/api/public/landing/hero/` | Hero section only |
| GET | `/api/public/landing/features/` | Features section |
| GET | `/api/public/landing/partners/` | Partners list |
| GET | `/api/public/landing/faq/` | FAQ items |
| GET | `/api/public/landing/testimonials/` | Testimonials |

### 🔧 Admin CMS (`/api/admin/cms/`)

> ⚠️ Requires admin authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/admin/cms/hero/` | List/Create hero sections |
| GET/PUT/DELETE | `/api/admin/cms/hero/{id}/` | Retrieve/Update/Delete hero |
| GET/POST | `/api/admin/cms/features/` | List/Create feature sections |
| GET/PUT/DELETE | `/api/admin/cms/features/{id}/` | Retrieve/Update/Delete features |
| GET/POST | `/api/admin/cms/feature-items/` | List/Create feature items |
| GET/PUT/DELETE | `/api/admin/cms/feature-items/{id}/` | Retrieve/Update/Delete feature item |
| GET/POST | `/api/admin/cms/partners/` | List/Create partners |
| GET/PUT/DELETE | `/api/admin/cms/partners/{id}/` | Retrieve/Update/Delete partner |
| GET/POST | `/api/admin/cms/faq/` | List/Create FAQ items |
| GET/PUT/DELETE | `/api/admin/cms/faq/{id}/` | Retrieve/Update/Delete FAQ |
| GET/POST | `/api/admin/cms/testimonials/` | List/Create testimonials |
| GET/PUT/DELETE | `/api/admin/cms/testimonials/{id}/` | Retrieve/Update/Delete testimonial |
| POST | `/api/admin/cms/invalidate-cache/` | Clear landing page cache |

### 👥 Admin Users (`/api/admin/users/`)

> ⚠️ Requires admin authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/users/` | List all users |
| POST | `/api/admin/users/` | Create user |
| GET | `/api/admin/users/{id}/` | Get user details |
| PUT/PATCH | `/api/admin/users/{id}/` | Update user |
| DELETE | `/api/admin/users/{id}/` | Delete user |

### 📍 Utilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/wilayas/` | List Algerian wilayas |
| GET | `/api/roles/` | List available user roles |
| GET | `/api/statuses/` | List user status options |

---

## Sample API Requests

### Register User

```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!",
    "password_confirm": "SecurePass123!",
    "first_name": "Ahmed",
    "last_name": "Benali",
    "phone": "+213555123456"
  }'
```

### Login

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!"
  }'
```

### Get Landing Page (French)

```bash
curl http://localhost:8000/api/public/landing/?lang=fr
```

### Create Hero Section (Admin)

```bash
curl -X POST http://localhost:8000/api/admin/cms/hero/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "title": {
        "fr": "Développez vos compétences",
        "en": "Develop Your Skills",
        "ar": "طوّر مهاراتك"
    },
    "subtitle": {
        "fr": "Formation en ligne de qualité",
        "en": "Quality Online Training",
        "ar": "تدريب عبر الإنترنت عالي الجودة"
    },
    "description": {
        "fr": "Rejoignez des milliers de professionnels",
        "en": "Join thousands of professionals",
        "ar": "انضم إلى آلاف المحترفين"
    },
    "is_active": true
  }'
```

### Create FAQ Item (Admin)

```bash
curl -X POST http://localhost:8000/api/admin/cms/faq/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "question": {
        "fr": "Comment puis-je m'\''inscrire ?",
        "en": "How can I register?",
        "ar": "كيف يمكنني التسجيل؟"
    },
    "answer": {
        "fr": "Cliquez sur le bouton S'\''inscrire et remplissez le formulaire.",
        "en": "Click the Register button and fill out the form.",
        "ar": "انقر على زر التسجيل واملأ النموذج."
    },
    "order": 1,
    "is_active": true
  }'
```

### Create Testimonial (Admin)

```bash
curl -X POST http://localhost:8000/api/admin/cms/testimonials/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "author_name": "Fatima Zahra El Amrani",
    "author_title": {
        "fr": "Développeuse Full Stack",
        "en": "Full Stack Developer",
        "ar": "مطورة Full Stack"
    },
    "content": {
        "fr": "Excellente plateforme de formation !",
        "en": "Excellent training platform!",
        "ar": "منصة تدريب ممتازة!"
    },
    "rating": 5,
    "order": 1,
    "is_active": true
  }'
```

---

## Project Structure

```
ooskillsbackend/
├── manage.py                 # Django management script
├── .env                      # Environment variables (not in git)
├── .gitignore
├── README.md
│
├── ooskillsbackend/          # Main Django project
│   ├── settings.py           # Django settings
│   ├── urls.py               # Root URL configuration
│   ├── wsgi.py               # WSGI entry point
│   └── asgi.py               # ASGI entry point
│
├── content/                  # Landing Page CMS app
│   ├── models.py             # Content models (Hero, Features, FAQ, etc.)
│   ├── serializers.py        # DRF serializers (Public & Admin)
│   ├── views.py              # API views and viewsets
│   ├── urls.py               # Content URL patterns
│   ├── permissions.py        # Custom permissions
│   ├── admin.py              # Django admin configuration
│   └── migrations/           # Database migrations
│
├── users/                    # User management app
│   ├── models.py             # Custom User model
│   ├── serializers.py        # User serializers
│   ├── views.py              # Auth & user views
│   ├── urls.py               # User URL patterns
│   ├── authentication.py     # Custom JWT authentication
│   ├── admin.py              # User admin configuration
│   └── management/
│       └── commands/         # Custom management commands
│           ├── create_supabase_user.py
│           └── sync_to_supabase.py
│
└── media/                    # Uploaded files
    ├── hero/                 # Hero background images
    ├── partners/             # Partner logos
    └── testimonials/         # Author profile images
```

---

## 🌍 Translation System

Content models use JSON fields for translations:

```python
{
    "fr": "Texte en français",
    "en": "English text",
    "ar": "النص العربي"
}
```

**Supported Languages:**
- `fr` - French (default)
- `en` - English
- `ar` - Arabic

**Fallback Order:** `fr → en → ar`

---

## 🔒 Authentication

The API uses **JWT (JSON Web Tokens)** for authentication:

1. **Access Token** - Short-lived (5-15 minutes)
2. **Refresh Token** - Long-lived (7 days)

Include the access token in requests:

```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

---

## 📝 License

MIT License

---

## 👥 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📧 Contact

OOSkills Team - [contact@ooskills.com](mailto:contact@ooskills.com)

Project Link: [https://github.com/ooware22/ooskills-backend](https://github.com/ooware22/ooskills-backend)
