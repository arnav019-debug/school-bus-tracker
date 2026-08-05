from fastapi import APIRouter
from app.api import auth, buses, students, drivers, routes

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(buses.router, prefix="/buses", tags=["Buses"])
api_router.include_router(students.router, prefix="/students", tags=["Students"])
api_router.include_router(drivers.router, prefix="/drivers", tags=["Drivers"])
api_router.include_router(routes.router, prefix="/routes", tags=["Routes"])
