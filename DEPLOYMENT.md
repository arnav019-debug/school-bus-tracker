# School Bus Tracker — Production Deployment & Operations Runbook

This guide contains end-to-end instructions for deploying and operating the School Bus Tracking System across the backend (FastAPI on Render), the managed database (Supabase PostgreSQL), and the cross-platform client (Flutter Android/iOS).

---

## 1. System Architecture

- **Backend API**: FastAPI (Python 3.11+, Pydantic v2, SQLAlchemy 2 async). Deployed on Render.
- **Production Database**: Supabase PostgreSQL (with PostGIS extensions for spatial data).
- **Test Database**: Strict in-memory SQLite (`sqlite+aiosqlite:///:memory:`) with safety guards ensuring live production databases are never touched by unit/integration test suites.
- **Push Notifications**: Firebase Cloud Messaging (FCM) via Firebase Admin SDK with automatic token lifecycle pruning, deduplication, and graceful local/mock fallback.
- **Mobile Client**: Flutter application (`mobile_app/`) supporting Admin, Teacher, Driver, and Parent roles with persistent JWT/Supabase sessions.

---

## 2. Supabase Database Migration Status & Runbook

**Current Live Database Status**:
- **Applied Revision**: `e5f6a7b8c9d0` (head).
- **Migration Status**: **Applied & Verified** on the live Supabase PostgreSQL database.
- **Full Linear Chain**: `f749d66e2a2a` -> `438934aedc4e` -> `8e29d71c4f10` -> `c3d4e5f6a7b8` -> `d4e5f6a7b8c9` -> `e5f6a7b8c9d0` (head).

### Verification Query (Run anytime to verify live state)
```bash
alembic current
# Output: e5f6a7b8c9d0 (head)
```

```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('attendance', 'routes', 'device_tokens', 'notification_logs', 'route_change_requests');
```

---

### Migration Reference (For New Environments / Staging)

To deploy or upgrade a fresh environment or staging database, run:

```bash
# Ensure your active DATABASE_URL points to your target PostgreSQL instance
export DATABASE_URL="postgresql+asyncpg://postgres:[YOUR-PASSWORD]@[YOUR-SUPABASE-HOST]:5432/postgres"

# Execute migration to head
alembic upgrade head
```

### Option B: Apply Migrations via Supabase SQL Editor

If you prefer applying raw SQL in the Supabase Dashboard SQL Editor, run this script (which covers the upgrade from `8e29d71c4f10` up to `e5f6a7b8c9d0`):

```sql
BEGIN;

-- 1. Upgrade 8e29d71c4f10 -> c3d4e5f6a7b8: add teacher_id to routes and attendance_date to attendance
ALTER TABLE routes ADD COLUMN IF NOT EXISTS teacher_id UUID;
ALTER TABLE routes ADD CONSTRAINT fk_routes_teacher_id FOREIGN KEY (teacher_id) REFERENCES profiles (id) ON DELETE SET NULL;

ALTER TABLE attendance ADD COLUMN IF NOT EXISTS attendance_date DATE;

-- Backfill existing attendance rows using scanned_at in Asia/Kolkata timezone
UPDATE attendance 
SET attendance_date = (scanned_at AT TIME ZONE 'Asia/Kolkata')::date 
WHERE attendance_date IS NULL;

-- Remove duplicates keeping latest record per (student_id, date, action_type)
DELETE FROM attendance
WHERE id NOT IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY student_id, attendance_date, action_type
            ORDER BY scanned_at DESC, id DESC
        ) as rnum
        FROM attendance
    ) t WHERE t.rnum = 1
);

ALTER TABLE attendance ALTER COLUMN attendance_date SET NOT NULL;
ALTER TABLE attendance ADD CONSTRAINT uq_attendance_student_date_action UNIQUE (student_id, attendance_date, action_type);

-- Drop old status CHECK constraint dynamically if exists
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public'
          AND cl.relname = 'attendance'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE attendance DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;
END $$;

-- Normalize legacy statuses
UPDATE attendance SET status = 'present' WHERE status IN ('boarded', 'dropped', 'disembarked');
ALTER TABLE attendance ADD CONSTRAINT attendance_status_check CHECK (status IN ('present', 'absent'));

-- 2. Upgrade c3d4e5f6a7b8 -> d4e5f6a7b8c9: add device_tokens and notification_logs
CREATE TABLE IF NOT EXISTS device_tokens (
    id UUID NOT NULL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    token VARCHAR(500) NOT NULL UNIQUE,
    platform VARCHAR(50) DEFAULT 'android' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_device_tokens_user_id ON device_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_device_tokens_token ON device_tokens (token);

CREATE TABLE IF NOT EXISTS notification_logs (
    id UUID NOT NULL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,
    data_payload JSON,
    status VARCHAR(50) DEFAULT 'sent' NOT NULL,
    error_message TEXT,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_notification_logs_user_id ON notification_logs (user_id);

-- 3. Upgrade d4e5f6a7b8c9 -> e5f6a7b8c9d0: add route_change_requests
CREATE TABLE IF NOT EXISTS route_change_requests (
    id UUID NOT NULL PRIMARY KEY,
    student_id UUID NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    requested_by UUID NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    target_route_id UUID NOT NULL REFERENCES routes (id) ON DELETE CASCADE,
    target_bus_id UUID REFERENCES buses (id) ON DELETE SET NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason VARCHAR(500) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    reviewed_by UUID REFERENCES profiles (id) ON DELETE SET NULL,
    review_notes VARCHAR(500),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT check_route_change_status CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_route_change_requests_student_id ON route_change_requests (student_id);
CREATE INDEX IF NOT EXISTS ix_route_change_requests_requested_by ON route_change_requests (requested_by);
CREATE INDEX IF NOT EXISTS ix_route_change_requests_target_route_id ON route_change_requests (target_route_id);
CREATE INDEX IF NOT EXISTS ix_route_change_requests_start_date ON route_change_requests (start_date);
CREATE INDEX IF NOT EXISTS ix_route_change_requests_end_date ON route_change_requests (end_date);

-- Update Alembic version table
UPDATE alembic_version SET version_num = 'e5f6a7b8c9d0';

COMMIT;
```

### Verification Query

Run this query to confirm that the schema is fully updated:

```sql
SELECT table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('attendance', 'routes', 'device_tokens', 'notification_logs', 'route_change_requests')
ORDER BY table_name, ordinal_position;
```

### Rollback Commands

If rollback is ever required:

```bash
# Downgrade route change requests
alembic downgrade d4e5f6a7b8c9

# Downgrade notifications
alembic downgrade c3d4e5f6a7b8

# Downgrade attendance adjustments
alembic downgrade 8e29d71c4f10
```

---

## 3. Backend Deployment (Render)

### Environment Variables
Configure these in the Render Dashboard (**Environment Settings**).

> [!IMPORTANT]
> **Only add environment variables if they are missing.** Never overwrite or modify your existing `DATABASE_URL` or `SUPABASE_*` credentials.
> - `CORS_ORIGINS` requires no setting (safe production defaults are automatically applied).
> - Custom SMTP is only needed if you wish to test the forgot-password recovery flow; Supabase's default sender is rate-limited to 3–4 emails/hour.

| Variable | Description | Requirement |
|---|---|---|
| `DATABASE_URL` | Supabase AsyncPG connection string (`postgresql+asyncpg://...`) | Copy from existing Render settings. |
| `ENVIRONMENT` | Deployment environment mode | Set to `production`. Local JWT auth is strictly disabled outside `development`/`test`. |
| `SECRET_KEY` | Server secret key for JWT signing outside dev/test | Set to a random string of at least 32 characters (generate via `openssl rand -hex 32`). Must never be committed or printed. |
| `PUBLIC_BASE_URL` | Canonical public HTTPS base URL | Set to `https://school-bus-tracker-crwb.onrender.com` |
| `PASSWORD_RESET_REDIRECT_URL` | Web reset page redirect destination | Set to `https://school-bus-tracker-crwb.onrender.com/reset-password` |
| `SUPABASE_URL` | Supabase Project URL (`https://xyz.supabase.co`) | Copy from existing Render settings. |
| `SUPABASE_KEY` | Supabase Anon Key (`eyJh...`) | Copy from existing Render settings. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role Key (`eyJh...`) | Copy from existing Render settings. |
| `SUPABASE_JWT_SECRET` | Supabase JWT Secret (from Supabase Settings > API) | Copy from existing Render settings / Supabase. |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Optional raw JSON string for Firebase service account | Optional; push notifications only. |
| `FIREBASE_PROJECT_ID` | Optional Firebase project ID | Optional; push notifications only. |

### Render Service Settings
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/docs`

---

## 4. Flutter Mobile App Build Guide

### Environment Configuration via `--dart-define`
The Flutter app automatically reads the target API URL using `String.fromEnvironment('API_BASE_URL')` configured in `mobile_app/lib/config/app_config.dart`.

To build for production against Render:
```bash
cd mobile_app
flutter build apk --release --dart-define=API_BASE_URL=https://school-bus-tracker-crwb.onrender.com
```

To build against local development:
```bash
cd mobile_app
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

### Android Release Signing

1. Copy the keystore template:
   ```bash
   cp mobile_app/android/key.properties.example mobile_app/android/key.properties
   ```
2. Populate `mobile_app/android/key.properties` with your upload keystore file path, key alias, and passwords.
3. Build the release bundle:
   ```bash
   flutter build appbundle --release --dart-define=API_BASE_URL=https://school-bus-tracker-crwb.onrender.com
   ```

---

## 5. Smoke Testing Setup & Role-by-Role Checklist

### Test Data Setup

1. **User Accounts**:
   - Register or create users using plus-aliases of your own Gmail (e.g. `YOURNAME+teacher@gmail.com`, `YOURNAME+driver@gmail.com`, `YOURNAME+parent@gmail.com`).
   - Use unique, strong passwords generated from your password manager.
   - When finished with testing, delete the test user accounts from Supabase Dashboard (**Authentication > Users**).

2. **Role Promotion (SQL only for roles)**:
   In the Supabase SQL Editor, run:
   ```sql
   UPDATE profiles SET role = 'teacher' WHERE email = 'YOURNAME+teacher@gmail.com';
   -- Check output: Must return "UPDATE 1". If "UPDATE 0", register that email in the app first, then rerun.

   UPDATE profiles SET role = 'driver' WHERE email = 'YOURNAME+driver@gmail.com';
   -- Check output: Must return "UPDATE 1". If "UPDATE 0", register that email in the app first, then rerun.
   ```

3. **Entity Creation (Via Admin Screens in the App)**:
   Log in with an Admin account (`YOURNAME+admin@gmail.com` or your existing admin login):
   - **Buses**: Open **View buses** $\to$ tap **+ Add Bus** $\to$ enter bus number (e.g. `BUS-01`) and license plate.
   - **Drivers**: Open **Manage drivers** $\to$ tap **+ Add Driver** $\to$ enter license number and phone linked to the driver user.
   - **Routes**: Open **Manage routes** $\to$ tap **+ Add Route** $\to$ enter route name, start location, and end location. Tap **Assign route** to assign the teacher and bus.
   - **Students**: Open **Manage students** $\to$ tap **+ Add Student** $\to$ enter student name, grade, select the parent, and assign the route.

---

### Role-by-Role Smoke Testing Checklist

- [ ] **Admin**:
  - Log in with Admin account.
  - Navigate to **Manage students**: verify student created and assigned to route and parent.
  - Navigate to **Manage routes**: verify route displays assigned teacher and bus.
  - Navigate to **Route change requests**: review pending parent requests.
  - View **Attendance Roster**: verify class attendance records can be inspected.

- [ ] **Teacher**:
  - Log in with `YOURNAME+teacher@gmail.com`.
  - Open **Teacher Attendance**: verify assigned route students appear for today (IST).
  - Date picker: confirm past dates within the last 7 days can be selected; verify future dates and dates older than 7 days are disabled.
  - Mark student **Present** or **Absent**: verify status updates immediately.

- [ ] **Parent**:
  - Log in with `YOURNAME+parent@gmail.com`.
  - Verify child information, pickup/dropoff stops, and assigned bus/driver details display properly.
  - Tap **View bus location**: test the **Follow Bus** toggle and recenter FAB.
  - Open **Route & bus change requests** $\to$ tap **+ New Request** $\to$ submit a request for tomorrow $\to$ verify request shows as `PENDING`.

- [ ] **Driver**:
  - Log in with `YOURNAME+driver@gmail.com`.
  - Open **Driver Mode**: select assigned bus.
  - Tap **Start sharing**: confirm location permissions prompt and live coordinates transmission (200 OK).
  - Tap **Stop sharing**: confirm GPS tracking gracefully terminates.

---

## 6. Automated Live Verification Suite

The repository includes a standalone, re-runnable live verification script (`scripts/verify_live.py`) designed to validate the live production system without modifying permanent records.

### What It Tests:
1. **Real User Logins**: Authenticates all 5 live demo accounts (Admin, Teacher, Driver, Parent A, Parent B) via `POST /api/v1/auth/login`.
2. **Security & Role Scoping**:
   - Confirms Admin has global read visibility across students and routes.
   - Confirms Parent A sees only their child, their child's route and bus, and that effective fields (`effective_route_id`, `effective_bus_id`, `effective_driver`) are populated.
   - Confirms Parent A cannot perform admin entity mutations (returns HTTP 403).
   - Confirms Parent B has 0 students and cannot access Parent A's student by ID (returns 403/404).
   - Confirms Driver and Teacher see only their assigned routes and rosters.
3. **Route Swap & Effective Roster Flow**:
   - Creates a temporary target route with a secondary bus.
   - Submits a route change request as Parent A and approves it as Admin.
   - Confirms Parent A's student view updates to show the target route and bus.
   - Confirms student is absent from original rosters and present on target rosters.
   - Confirms Parent A has live bus tracking access to the temporary bus.
4. **Reversible Cleanup**:
   - Deletes the temporary route change request and target route by exact ID.
   - Confirms student and rosters revert back to their original state.

### How to Run:
Ensure `demo-credentials.txt` is present locally at `~/sbt-backups/demo-credentials.txt` (or specify via `--credentials` flag):

```bash
# Execute verification against the live Render deployment
python3 scripts/verify_live.py

# Or with custom credentials path
python3 scripts/verify_live.py --credentials /path/to/demo-credentials.txt
```

---

## 7. Demo Data Cleanup Guide (`demo-cleanup.py`)

When testing is complete and the live environment needs to be reset to its clean production baseline, run the demo cleanup script stored in `~/sbt-backups/demo-cleanup.py`:

```bash
cd ~/sbt-backups
python3 demo-cleanup.py
```

### What `demo-cleanup.py` Does:
- Reads database and auth service credentials strictly in-process.
- Removes all records created for live demo verification by exact ID:
  - Demo Student (`53d5a13f-b017-4eb1-821d-6e23989c7c93`)
  - Demo Route (`fb04b655-a9a8-4c0e-b81c-1e17c75fd0b6`)
  - Demo Driver (`7b783d5f-ab8e-4353-b2cc-f863e056e4ef`)
  - Demo Bus (`b6c53332-5633-42be-933a-84b1683712b1`)
  - Demo Users in `auth.users` and `public.profiles` (`arnavg791+demo_*@gmail.com`)
  - Any temporary attendance, GPS, device token, or notification log rows.
- Verifies post-cleanup table row counts to confirm zero residual artifacts.

---

## 8. Secret Rotation Runbook

To maintain security hygiene or remediate suspected credential exposure, follow this rotation order:

### 1. Supabase Database Password (`DATABASE_URL`)
1. In Supabase Dashboard: Navigate to **Project Settings > Database > Database password**.
2. Click **Reset database password** and copy the new password.
3. Update `DATABASE_URL` in the Render Dashboard (**Environment > Environment Variables**):
   ```
   postgresql+asyncpg://postgres:[NEW_PASSWORD]@[HOST]:5432/postgres
   ```
4. Render will trigger a redeploy automatically.

### 2. Supabase API Keys & JWT Secret (`SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`)
1. In Supabase Dashboard: Navigate to **Project Settings > API**.
2. Under **Project API keys**, click **Generate new JWT secret** (Caution: this invalidates all current user sessions).
3. Copy the new `anon` key, `service_role` key, and `JWT Secret`.
4. Update the corresponding Render environment variables:
   - `SUPABASE_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_JWT_SECRET`
5. Save changes in Render; the backend will redeploy and pick up the new keys.

### 3. Backend Secret Key (`SECRET_KEY`)
1. Generate a new high-entropy secret key locally:
   ```bash
   openssl rand -hex 32
   ```
2. In Render Dashboard, update `SECRET_KEY` with the generated value.
3. Render will redeploy automatically.

### 4. Firebase Service Account (`FIREBASE_SERVICE_ACCOUNT_JSON`)
1. In Firebase Console: Open **Project Settings > Service accounts**.
2. Under **Firebase Admin SDK**, click **Generate new private key**.
3. Copy the contents of the downloaded JSON file to clipboard using `pbcopy`:
   ```bash
   pbcopy < ~/Downloads/school-bus-tracker-*.json
   ```
4. In Render Dashboard, update `FIREBASE_SERVICE_ACCOUNT_JSON` by pasting clipboard content.
5. Move the key to `~/sbt-backups/` (`chmod 600`) and delete the file from `~/Downloads`.

---

## 9. Operational Considerations & Known Limitations

1. **Render Free-Tier Spin-Down (Cold Starts)**:
   - On the Render Free instance type, services automatically spin down after 15 minutes of inbound HTTP inactivity.
   - The first request following dormancy will experience a cold-start delay of approximately 45–60 seconds while the container initializes and connects to Supabase.
   - **Mitigation**: The Flutter mobile client implements `ColdStartHttpClient` across all critical authentication and initial data loading flows with extended 60-second timeouts, automatic retry logic on 502/503/504 gateway responses, and an in-app visual indicator (*"Waking up the server, please wait..."*) to keep users informed.
2. **Supabase Default Email Sender Rate Limits**:
   - The default Supabase built-in email service is subject to strict rate limits (e.g., 3 emails per hour for password resets and verification).
   - In production environments with high user volumes, configure custom SMTP in **Authentication > Email Settings > Custom SMTP Provider** (e.g., SendGrid, Resend, AWS SES).
3. **Demo Data Management**:
   - Demo accounts and records exist on the live database strictly for system verification and mobile testing.
   - Demo records are clearly isolated, carrying identifiable names and plus-aliased emails (`arnavg791+demo_*@gmail.com`).
   - Run `python3 demo-cleanup.py` from `~/sbt-backups/` whenever you wish to remove all demo data.

