#!/usr/bin/env python3
"""
Re-runnable Live Verification Script for School Bus Tracker
Runs live role verification, security scoping, and swap flow against the live deployment.
Reads credentials strictly from local ~/sbt-backups/demo-credentials.txt (never commits secrets).

Usage:
    python3 scripts/verify_live.py
    python3 scripts/verify_live.py --credentials /path/to/demo-credentials.txt
"""

import os
import sys
import argparse
import datetime
from datetime import date
from typing import Dict, Any, Optional
import requests

def parse_credentials(filepath: str) -> Dict[str, Any]:
    if not os.path.exists(filepath):
        print(f"[ERROR] Credentials file not found: {filepath}", file=sys.stderr)
        print("Ensure ~/sbt-backups/demo-credentials.txt exists before running.", file=sys.stderr)
        sys.exit(1)

    config: Dict[str, Any] = {
        "base_url": "https://school-bus-tracker-crwb.onrender.com",
        "accounts": {},
        "records": {}
    }

    current_role: Optional[str] = None
    account_buffer: Dict[str, str] = {}

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("BASE_URL:"):
                config["base_url"] = line.split(":", 1)[1].strip()
            elif line.startswith("Role:"):
                if current_role and account_buffer:
                    config["accounts"][current_role] = account_buffer
                    account_buffer = {}
                current_role = line.split(":", 1)[1].strip().upper()
            elif line.startswith("Name:") and current_role:
                account_buffer["name"] = line.split(":", 1)[1].strip()
                if "Parent A" in account_buffer["name"]:
                    current_role = "PARENT_A"
                elif "Parent B" in account_buffer["name"]:
                    current_role = "PARENT_B"
            elif line.startswith("Email:") and current_role:
                account_buffer["email"] = line.split(":", 1)[1].strip()
            elif line.startswith("Password:") and current_role:
                account_buffer["password"] = line.split(":", 1)[1].strip()
            elif line.startswith("User ID:") and current_role:
                account_buffer["user_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("Bus ID:"):
                config["records"]["bus_id"] = line.split(":", 1)[1].split()[0].strip()
            elif line.startswith("Driver ID:"):
                config["records"]["driver_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("Route ID:"):
                config["records"]["route_id"] = line.split(":", 1)[1].split()[0].strip()
            elif line.startswith("Student ID:"):
                config["records"]["student_id"] = line.split(":", 1)[1].split()[0].strip()

        if current_role and account_buffer:
            config["accounts"][current_role] = account_buffer

    return config

def login(base_url: str, email: str, password: str) -> str:
    login_url = f"{base_url}/api/v1/auth/login"
    resp = requests.post(
        login_url,
        json={"email": email, "password": password},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=60
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed for {email} ({resp.status_code}): {resp.text}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access token returned for {email}")
    return token

def run_verification(credentials_path: str):
    print("=" * 70)
    print("SCHOOL BUS TRACKER - LIVE VERIFICATION SUITE")
    print(f"Timestamp: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 70)

    config = parse_credentials(credentials_path)
    base_url = config["base_url"]
    accounts = config["accounts"]
    records = config["records"]

    print(f"[CONFIG] Live Target: {base_url}")
    print(f"[CONFIG] Accounts Loaded: {list(accounts.keys())}")
    print(f"[CONFIG] Known Demo Records: {records}")
    print()

    # Step 1: Real Logins
    print("--- [STAGE 1] Authenticating Live Demo Accounts ---")
    tokens: Dict[str, str] = {}
    headers: Dict[str, Dict[str, str]] = {}

    for role_key in ["ADMIN", "TEACHER", "DRIVER", "PARENT_A", "PARENT_B"]:
        acct = accounts.get(role_key)
        if not acct:
            raise RuntimeError(f"Missing account credentials for {role_key}")
        email = acct["email"]
        token = login(base_url, email, acct["password"])
        tokens[role_key] = token
        headers[role_key] = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        print(f"  [PASS] {role_key:8s} ({email}) logged in successfully.")

    print()

    # Step 2: Role Scoping & Permission Matrix Audit
    print("--- [STAGE 2] Auditing Live Scoping & Security Rules ---")
    
    # 2.1 Admin: Global Read Access
    r_admin_students = requests.get(f"{base_url}/api/v1/students", headers=headers["ADMIN"], timeout=30)
    assert r_admin_students.status_code == 200, f"Admin students failed: {r_admin_students.text}"
    admin_students = r_admin_students.json()
    assert len(admin_students) >= 1, "Admin should see enrolled students"
    print(f"  [PASS] Admin can read all students (count: {len(admin_students)})")

    r_admin_routes = requests.get(f"{base_url}/api/v1/routes", headers=headers["ADMIN"], timeout=30)
    assert r_admin_routes.status_code == 200, f"Admin routes failed: {r_admin_routes.text}"
    admin_routes = r_admin_routes.json()
    assert len(admin_routes) >= 1, "Admin should see all routes"
    print(f"  [PASS] Admin can read all routes (count: {len(admin_routes)})")

    # 2.2 Parent A: Scoped strictly to own child
    r_parent_students = requests.get(f"{base_url}/api/v1/students", headers=headers["PARENT_A"], timeout=30)
    assert r_parent_students.status_code == 200, f"Parent A students failed: {r_parent_students.text}"
    p_students = r_parent_students.json()
    assert len(p_students) == 1, f"Parent A must see exactly 1 student, got: {len(p_students)}"
    stu = p_students[0]
    student_id = stu["id"]
    orig_route_id = stu.get("route_id")
    orig_bus_id = stu.get("effective_bus_id")
    print(f"  [PASS] Parent A sees exactly own student: {stu.get('first_name')} {stu.get('last_name')} (ID: {student_id})")
    assert "effective_route_id" in stu, "Student response must expose effective_route_id"
    assert "effective_bus_id" in stu, "Student response must expose effective_bus_id"
    assert "effective_driver" in stu, "Student response must expose effective_driver"
    print(f"  [PASS] Parent A student response includes effective_route_id, effective_bus_id, effective_driver")

    # Parent A routes and buses scoped
    r_parent_routes = requests.get(f"{base_url}/api/v1/routes", headers=headers["PARENT_A"], timeout=30)
    assert r_parent_routes.status_code == 200
    p_routes = r_parent_routes.json()
    assert len(p_routes) == 1, f"Parent A should see only child's route, got {len(p_routes)}"
    assert p_routes[0]["id"] == orig_route_id, "Route ID must match child's route"
    print(f"  [PASS] Parent A sees only child's assigned route ({p_routes[0].get('name')})")

    # Parent A mutation protection (403 Forbidden)
    r_parent_mutate = requests.post(
        f"{base_url}/api/v1/students",
        headers=headers["PARENT_A"],
        json={"first_name": "Leak", "last_name": "Test", "route_id": orig_route_id},
        timeout=30
    )
    assert r_parent_mutate.status_code == 403, f"Parent A should be 403 forbidden to create students, got {r_parent_mutate.status_code}"
    print("  [PASS] Parent A mutation blocked (POST /students -> 403 Forbidden)")

    # 2.3 Parent B: Isolation & Cross-Family Leak Prevention
    r_parent_b_students = requests.get(f"{base_url}/api/v1/students", headers=headers["PARENT_B"], timeout=30)
    assert r_parent_b_students.status_code == 200
    p_b_students = r_parent_b_students.json()
    assert len(p_b_students) == 0, f"Parent B should have 0 students, got {len(p_b_students)}"
    print("  [PASS] Parent B sees 0 students (clean isolation)")

    r_parent_b_leak = requests.get(f"{base_url}/api/v1/students/{student_id}", headers=headers["PARENT_B"], timeout=30)
    assert r_parent_b_leak.status_code in (403, 404), f"Parent B accessing Parent A child must fail, got {r_parent_b_leak.status_code}"
    print(f"  [PASS] Cross-family student access rejected (status {r_parent_b_leak.status_code})")

    # 2.4 Driver: Route & Bus Scoping
    r_driver_routes = requests.get(f"{base_url}/api/v1/routes", headers=headers["DRIVER"], timeout=30)
    assert r_driver_routes.status_code == 200
    d_routes = r_driver_routes.json()
    assert len(d_routes) == 1, f"Driver must see only assigned route, got {len(d_routes)}"
    print(f"  [PASS] Driver sees only assigned route: {d_routes[0].get('name')}")

    # Driver mutation attempt blocked
    r_driver_mutate = requests.post(
        f"{base_url}/api/v1/routes",
        headers=headers["DRIVER"],
        json={"name": "Forbidden Driver Route", "start_location": "X", "end_location": "Y"},
        timeout=30
    )
    assert r_driver_mutate.status_code == 403, f"Driver cannot create routes, got {r_driver_mutate.status_code}"
    print("  [PASS] Driver mutation blocked (POST /routes -> 403 Forbidden)")

    # 2.5 Teacher: Assigned Route Scoping
    r_teacher_routes = requests.get(f"{base_url}/api/v1/routes", headers=headers["TEACHER"], timeout=30)
    assert r_teacher_routes.status_code == 200
    t_routes = r_teacher_routes.json()
    assert len(t_routes) == 1, f"Teacher must see assigned route, got {len(t_routes)}"
    print(f"  [PASS] Teacher sees assigned route: {t_routes[0].get('name')}")

    print()

    # Step 3: Temporary Route Swap Flow & Full Lifecycle Verification
    print("--- [STAGE 3] Route Swap Request & Roster Verification Flow ---")
    
    # 3.1 Verify Pre-Swap Rosters
    r_teach_roster = requests.get(f"{base_url}/api/v1/attendance/roster", headers=headers["TEACHER"], timeout=30)
    assert r_teach_roster.status_code == 200, r_teach_roster.text
    teach_roster_ids = [s["student_id"] for s in r_teach_roster.json()]
    assert student_id in teach_roster_ids, "Student must be on Teacher roster before swap"
    print("  [PRE-SWAP] Student present on Demo Teacher roster: OK")

    r_driver_roster = requests.get(f"{base_url}/api/v1/attendance/roster", headers=headers["DRIVER"], timeout=30)
    assert r_driver_roster.status_code == 200, r_driver_roster.text
    driver_roster_ids = [s["student_id"] for s in r_driver_roster.json()]
    assert student_id in driver_roster_ids, "Student must be on Demo Driver roster before swap"
    print("  [PRE-SWAP] Student present on Demo Driver roster: OK")

    # 3.2 Create temporary target route as Admin using second pre-existing bus
    # Look up second bus ID
    r_all_buses = requests.get(f"{base_url}/api/v1/buses", headers=headers["ADMIN"], timeout=30)
    assert r_all_buses.status_code == 200
    all_buses = r_all_buses.json()
    target_bus = next((b for b in all_buses if b["id"] != orig_bus_id), None)
    assert target_bus is not None, "Need secondary bus in database for target swap"
    target_bus_id = target_bus["id"]

    temp_route_payload = {
        "name": "DEMO Live Verification Target Route",
        "start_location": "Verification Point A",
        "end_location": "Verification Point B",
        "bus_id": target_bus_id,
        "teacher_id": accounts["TEACHER"]["user_id"],
        "waypoints": []
    }
    r_create_target = requests.post(f"{base_url}/api/v1/routes", headers=headers["ADMIN"], json=temp_route_payload, timeout=30)
    assert r_create_target.status_code == 201, f"Failed creating temp target route: {r_create_target.text}"
    temp_target_route = r_create_target.json()
    temp_target_route_id = temp_target_route["id"]
    print(f"  [SWAP] Created temporary target route: {temp_target_route_id} with bus {target_bus_id}")

    temp_swap_id: Optional[str] = None
    try:
        # 3.3 Parent A submits route change request for today
        today_iso = date.today().isoformat()
        swap_payload = {
            "student_id": student_id,
            "target_route_id": temp_target_route_id,
            "target_bus_id": target_bus_id,
            "start_date": today_iso,
            "end_date": today_iso,
            "reason": "Live automated verification test run"
        }
        r_sub_swap = requests.post(f"{base_url}/api/v1/route-change-requests", headers=headers["PARENT_A"], json=swap_payload, timeout=30)
        assert r_sub_swap.status_code == 201, f"Failed submitting swap request: {r_sub_swap.text}"
        temp_swap = r_sub_swap.json()
        temp_swap_id = temp_swap["id"]
        print(f"  [SWAP] Parent A submitted swap request (ID: {temp_swap_id}, status: {temp_swap['status']})")

        # 3.4 Admin approves the swap request
        r_approve = requests.put(
            f"{base_url}/api/v1/route-change-requests/{temp_swap_id}/approve",
            headers=headers["ADMIN"],
            json={"review_notes": "Live test automated approval"},
            timeout=30
        )
        assert r_approve.status_code == 200, f"Approval failed: {r_approve.text}"
        print("  [SWAP] Admin approved swap request: status is now 'approved'")

        # 3.5 Verify student effective fields updated
        r_stu_swap = requests.get(f"{base_url}/api/v1/students/{student_id}", headers=headers["PARENT_A"], timeout=30)
        assert r_stu_swap.status_code == 200
        stu_swap = r_stu_swap.json()
        assert stu_swap.get("route_id") == orig_route_id, "Permanent route must remain unchanged"
        assert stu_swap.get("effective_route_id") == temp_target_route_id, "effective_route_id must reflect target route"
        assert stu_swap.get("effective_bus_id") == target_bus_id, "effective_bus_id must reflect target bus"
        print("  [SWAP] Parent view verified: student reflects temporary target route & target bus")

        # 3.6 Verify Parent A bus tracking access
        r_target_bus = requests.get(f"{base_url}/api/v1/buses/{target_bus_id}", headers=headers["PARENT_A"], timeout=30)
        assert r_target_bus.status_code == 200, f"Parent should have tracking access to target bus: {r_target_bus.text}"
        print("  [SWAP] Parent tracking access granted to target bus: OK")

    finally:
        # Step 4: Strict Cleanup
        print("\n--- [STAGE 4] Reversible Cleanup & Restoration ---")
        if temp_swap_id:
            r_del_swap = requests.delete(f"{base_url}/api/v1/route-change-requests/{temp_swap_id}", headers=headers["ADMIN"], timeout=30)
            print(f"  [CLEANUP] Deleted swap request {temp_swap_id}: HTTP {r_del_swap.status_code}")

        if temp_target_route_id:
            r_del_route = requests.delete(f"{base_url}/api/v1/routes/{temp_target_route_id}", headers=headers["ADMIN"], timeout=30)
            print(f"  [CLEANUP] Deleted temporary target route {temp_target_route_id}: HTTP {r_del_route.status_code}")

    # 4.1 Verify Student fields restored to original
    r_stu_revert = requests.get(f"{base_url}/api/v1/students/{student_id}", headers=headers["PARENT_A"], timeout=30)
    assert r_stu_revert.status_code == 200
    stu_revert = r_stu_revert.json()
    assert stu_revert.get("effective_route_id") == orig_route_id, "Effective route must revert back to permanent"
    assert stu_revert.get("effective_bus_id") == orig_bus_id, "Effective bus must revert back to permanent"
    print("  [PASS] Student effective route and bus reverted back to original")

    # 4.2 Verify Rosters restored
    r_teach_restored = requests.get(f"{base_url}/api/v1/attendance/roster", headers=headers["TEACHER"], timeout=30)
    assert r_teach_restored.status_code == 200
    assert student_id in [s["student_id"] for s in r_teach_restored.json()], "Student must be back on teacher roster"

    r_driver_restored = requests.get(f"{base_url}/api/v1/attendance/roster", headers=headers["DRIVER"], timeout=30)
    assert r_driver_restored.status_code == 200
    assert student_id in [s["student_id"] for s in r_driver_restored.json()], "Student must be back on driver roster"
    print("  [PASS] Teacher and Driver rosters fully restored")

    print("\n" + "=" * 70)
    print("ALL LIVE VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live verification of School Bus Tracker backend.")
    parser.add_argument(
        "--credentials",
        default=os.path.expanduser("~/sbt-backups/demo-credentials.txt"),
        help="Path to local demo-credentials.txt"
    )
    args = parser.parse_args()
    try:
        run_verification(args.credentials)
    except Exception as e:
        print(f"\n[FATAL ERROR] Live verification failed: {e}", file=sys.stderr)
        sys.exit(1)
