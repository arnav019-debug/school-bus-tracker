-- ==========================================
-- School Bus Tracking System - Sample Seed Data
-- ==========================================

-- 1. Insert Sample Admin/Staff & Parent Profiles (assuming auth user IDs or mock profiles)
-- Note: Replace these UUIDs with actual auth.users IDs after signing up in Supabase Auth if needed.

-- Sample Buses
INSERT INTO public.buses (id, bus_number, license_plate, capacity, status)
VALUES 
    ('11111111-1111-1111-1111-111111111111', 'BUS-101', 'AB-123-CD', 40, 'active'),
    ('22222222-2222-2222-2222-222222222222', 'BUS-102', 'EF-456-GH', 36, 'active')
ON CONFLICT (id) DO NOTHING;

-- Sample Drivers
INSERT INTO public.drivers (id, license_number, phone, status)
VALUES 
    ('33333333-3333-3333-3333-333333333333', 'DL-98765432', '+15550192834', 'active'),
    ('44444444-4444-4444-4444-444444444444', 'DL-12345678', '+15550195678', 'active')
ON CONFLICT (id) DO NOTHING;

-- Link Driver to Bus
UPDATE public.buses 
SET driver_id = '33333333-3333-3333-3333-333333333333' 
WHERE id = '11111111-1111-1111-1111-111111111111';

-- Sample Routes
INSERT INTO public.routes (id, name, bus_id, driver_id, start_location, end_location, waypoints, scheduled_start_time, scheduled_end_time, status)
VALUES 
    ('55555555-5555-5555-5555-555555555555', 'Morning Pickup - North Route', '11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', 'North Depot', 'Central School', '[{"stop_name": "Pine St & 5th Ave", "lat": 37.7749, "lng": -122.4194}, {"stop_name": "Oak St & 10th Ave", "lat": 37.7833, "lng": -122.4167}]'::jsonb, '07:00:00', '08:15:00', 'planned')
ON CONFLICT (id) DO NOTHING;

-- Sample Students
INSERT INTO public.students (id, first_name, last_name, grade, route_id, pickup_stop, dropoff_stop, qr_code_id)
VALUES 
    ('66666666-6666-6666-6666-666666666666', 'Alex', 'Johnson', 'Grade 4', '55555555-5555-5555-5555-555555555555', 'Pine St & 5th Ave', 'Central School', 'QR-ALEX-001'),
    ('77777777-7777-7777-7777-777777777777', 'Emma', 'Davis', 'Grade 5', '55555555-5555-5555-5555-555555555555', 'Oak St & 10th Ave', 'Central School', 'QR-EMMA-002')
ON CONFLICT (id) DO NOTHING;

-- Sample GPS Log
INSERT INTO public.gps_logs (bus_id, route_id, latitude, longitude, speed, heading)
VALUES 
    ('11111111-1111-1111-1111-111111111111', '55555555-5555-5555-5555-555555555555', 37.774920, -122.419415, 32.5, 180.0);
