# models.py
from pydantic import BaseModel
from typing import List, Optional

class ChatQuery(BaseModel):
    question: str

class Stop(BaseModel):
    address: str
    label: Optional[str] = None

class RouteOptimizationRequest(BaseModel):
    origin: str
    stops: List[Stop]
    destination: str
    routeName: Optional[str] = "Rota sem nome"

class MaintenanceReport(BaseModel):
    vehicle_id: str
    driver_report: str
    current_km: int