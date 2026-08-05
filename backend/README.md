# School Bus Tracker - FastAPI Backend

A high-performance asynchronous FastAPI backend connected to Supabase PostgreSQL, featuring JWT authentication and complete CRUD REST APIs for **Buses**, **Students**, **Drivers**, and **Routes**.

## Features

- **FastAPI & Async SQLAlchemy**: Async database connection supporting Supabase PostgreSQL and SQLite fallback.
- **JWT Authentication**: Integration with Supabase Auth & JWT tokens with `/api/v1/auth/register`, `/api/v1/auth/login`, and `/api/v1/auth/me`.
- **Buses CRUD API**: `/api/v1/buses` (List with filters, Create, Get by ID, Update, Delete).
- **Students CRUD API**: `/api/v1/students` (List with filters, Create, Get by ID, Update, Delete).
- **Drivers CRUD API**: `/api/v1/drivers` (List with filters, Create, Get by ID, Update, Delete).
- **Routes CRUD API**: `/api/v1/routes` (List with filters, Create, Get by ID, Update, Delete).
- **Interactive Documentation**: Auto-generated Swagger UI at `/docs` and ReDoc at `/redoc`.

---

## Setup & Local Execution

### 1. Environment Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and enter your Supabase credentials:

```bash
cp .env.example .env
```

To connect to your live Supabase Postgres database:
```env
SUPABASE_URL="https://<your-project-ref>.supabase.co"
SUPABASE_KEY="<your-anon-or-service-role-key>"
SUPABASE_JWT_SECRET="<your-supabase-jwt-secret>"
DATABASE_URL="postgresql+asyncpg://postgres:<your-db-password>@db.<your-project-ref>.supabase.co:5432/postgres"
```

### 3. Run the Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

Access the interactive API documentation at:
- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

---

## Running Automated Tests

```bash
pytest tests/ -v
```
