from datetime import date, datetime
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Float, ForeignKey, JSON, Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .db import Base


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    locations = relationship("Location", back_populates="company", cascade="all, delete")
    users = relationship("User", back_populates="company", cascade="all, delete")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    company = relationship("Company", back_populates="users")


class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    day = Column(Date, nullable=False)
    name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("location_id", "day", name="uix_loc_day"),)


class Location(Base):
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    rule_config = Column(JSON, nullable=False, default=dict)
    company = relationship("Company", back_populates="locations")
    employees = relationship("Employee", back_populates="location", cascade="all, delete")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    emp_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    gender = Column(String, nullable=False, default="M")  # M / F / O
    joining_date = Column(Date, nullable=False)
    exit_date = Column(Date, nullable=True)
    monthly_salary = Column(Float, nullable=False, default=0.0)
    opening_leave = Column(Float, nullable=False, default=0.0)
    location = relationship("Location", back_populates="employees")


class AttendanceRecord(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    day = Column(Date, nullable=False)
    code = Column(String(1), nullable=False)  # A/B/C/D/E/F/G
    worked_on_holiday = Column(Boolean, default=False)  # flags C/D that were actually worked


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    results = relationship("PayrollResult", back_populates="run", cascade="all, delete")


class PayrollResult(Base):
    __tablename__ = "payroll_results"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("payroll_runs.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    payload = Column(JSON, nullable=False)  # full calc detail
    run = relationship("PayrollRun", back_populates="results")
