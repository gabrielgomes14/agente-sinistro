# models.py
from pydantic import BaseModel
from typing import List, Optional

class ChatQuery(BaseModel):
    question: str

class MaintenanceReport(BaseModel):
    vehicle_id: str
    driver_report: str
    current_km: int