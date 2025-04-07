from pydantic import BaseModel
from typing import Optional, List, Union, Dict, Any
from datetime import datetime


class RoleBase(BaseModel):
    roleName: str
    description: Optional[str] = None


class UserBase(BaseModel):
    name: str
    login: str
    role_id: int


class SensorBase(BaseModel):
    sensor_name: str
    location: int
    active: bool


class SensorOverview(SensorBase):
    id: int
    
    class Config:
        orm_mode = True


class CurrentValueData(BaseModel):
    id: int
    time: datetime
    value: float
    sensors_id: int

    class Config:
        orm_mode = True


class EquipmentSettingData(BaseModel):
    id: int
    sensor_id: int
    min_value: float
    max_value: float

    class Config:
        orm_mode = True


class EventData(BaseModel):
    id: int
    time: datetime
    description: str
    sensors_id: Optional[int] = None
    users_id: Optional[int] = None
    sensor_name: Optional[str] = None

    class Config:
        orm_mode = True


class ExtruderSensorData(BaseModel):
    id: int
    sensor_name: str
    location: str
    value: float
    time: datetime
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: Optional[str] = None
    status: str = "normal"

    class Config:
        orm_mode = True


class ExtruderStats(BaseModel):
    temperature: Dict[str, Any]
    move_speed: Dict[str, Any]
    isolation_thickness: Dict[str, Any]
    cable_core_profile: Dict[str, Any]


class LoginRequest(BaseModel):
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"