-- ==========================================
-- School Bus Tracking System - Database Schema
-- Compatible with Supabase PostgreSQL & Auth
-- ==========================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------
-- 1. USERS / PROFILES TABLE
-- Extends Supabase auth.users or functions as user table
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'parent', 'driver')),
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Automatic Profile Creation Trigger for Supabase Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, role, phone)
    VALUES (
        new.id,
        new.email,
        COALESCE(new.raw_user_meta_data->>'full_name', new.email),
        COALESCE(new.raw_user_meta_data->>'role', 'parent'),
        new.raw_user_meta_data->>'phone'
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger execution on auth.users insert
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ------------------------------------------
-- 2. DRIVERS TABLE
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.drivers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    license_number TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'on_duty')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------
-- 3. BUSES TABLE
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.buses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_number TEXT UNIQUE NOT NULL,
    license_plate TEXT UNIQUE NOT NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'out_of_service')),
    driver_id UUID REFERENCES public.drivers(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------
-- 4. ROUTES TABLE
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    bus_id UUID REFERENCES public.buses(id) ON DELETE SET NULL,
    driver_id UUID REFERENCES public.drivers(id) ON DELETE SET NULL,
    start_location TEXT NOT NULL,
    end_location TEXT NOT NULL,
    waypoints JSONB DEFAULT '[]'::jsonb,
    scheduled_start_time TIME,
    scheduled_end_time TIME,
    status TEXT DEFAULT 'planned' CHECK (status IN ('planned', 'in_progress', 'completed', 'cancelled')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------
-- 5. STUDENTS TABLE
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    grade TEXT,
    parent_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    route_id UUID REFERENCES public.routes(id) ON DELETE SET NULL,
    pickup_stop TEXT,
    dropoff_stop TEXT,
    qr_code_id TEXT UNIQUE DEFAULT gen_random_uuid()::text,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------
-- 6. GPS LOGS TABLE (High Frequency Tracking)
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.gps_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bus_id UUID NOT NULL REFERENCES public.buses(id) ON DELETE CASCADE,
    route_id UUID REFERENCES public.routes(id) ON DELETE SET NULL,
    latitude DECIMAL(10, 8) NOT NULL,
    longitude DECIMAL(11, 8) NOT NULL,
    speed DECIMAL(5, 2) DEFAULT 0.0,
    heading DECIMAL(5, 2),
    timestamp TIMESTAMPTZ DEFAULT now()
);

-- Index for real-time location queries
CREATE INDEX IF NOT EXISTS idx_gps_logs_bus_timestamp ON public.gps_logs(bus_id, timestamp DESC);

-- ------------------------------------------
-- 7. ATTENDANCE TABLE (Scan / Boarding Events)
-- ------------------------------------------
CREATE TABLE IF NOT EXISTS public.attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    bus_id UUID REFERENCES public.buses(id) ON DELETE SET NULL,
    route_id UUID REFERENCES public.routes(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('boarded', 'disembarked', 'absent')),
    action_type TEXT NOT NULL CHECK (action_type IN ('pickup', 'dropoff')),
    scanned_at TIMESTAMPTZ DEFAULT now(),
    scanned_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8)
);

-- Index for student attendance history
CREATE INDEX IF NOT EXISTS idx_attendance_student_scanned ON public.attendance(student_id, scanned_at DESC);

-- ------------------------------------------
-- Row Level Security (RLS) Enablement
-- ------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gps_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
