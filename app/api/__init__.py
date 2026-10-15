from fastapi import APIRouter
from app.api import auth, buses, students, drivers, routes, attendance, notifications, route_change_requests

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(buses.router, prefix="/buses", tags=["Buses"])
api_router.include_router(students.router, prefix="/students", tags=["Students"])
api_router.include_router(drivers.router, prefix="/drivers", tags=["Drivers"])
api_router.include_router(routes.router, prefix="/routes", tags=["Routes"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["Attendance"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(route_change_requests.router, prefix="/route-change-requests", tags=["Route Change Requests"])
