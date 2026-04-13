from datetime import date
from typing import Any, Optional
from pydantic import BaseModel, Field


class CompanyIn(BaseModel):
    name: str


class CompanyOut(CompanyIn):
    id: int
    class Config: from_attributes = True


class LocationIn(BaseModel):
    company_id: int
    code: str
    name: str
    rule_config: dict[str, Any] = Field(default_factory=dict)


class LocationOut(LocationIn):
    id: int
    class Config: from_attributes = True


class EmployeeIn(BaseModel):
    location_id: int
    emp_code: str
    name: str
    gender: str = "M"
    joining_date: date
    exit_date: Optional[date] = None
    monthly_salary: float = 0
    opening_leave: float = 0


class EmployeeOut(EmployeeIn):
    id: int
    class Config: from_attributes = True


class PayrollRunIn(BaseModel):
    location_id: int
    month: int
    year: int
