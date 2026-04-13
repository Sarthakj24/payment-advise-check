"""Seed a sample company, user, location, employees, holidays, attendance."""
from datetime import date
from pathlib import Path
from .db import SessionLocal
from . import models, auth


SAMPLE_RULE_CONFIG = {
    "week_pattern": "6day",
    "week_off_day": 6,
    "approved_leaves_per_month": 1.5,
    "leave_carry_forward": "rollover",
    "female_extra_leave": 1,
    "excess_leave_to_absent": True,
    "holiday_work_multiplier": 2.0,
    "sandwich_rule": True,
    "exit_trailing_absence_unpaid": True,
    "attendance_starts_on_join_date": True,
    "triggers": {
        "immediate_leave_after_joining_days": 7,
        "consecutive_leave_days": 2,
    },
    "checks": ["N + approved_leave - E == L", "H == DM"],
}


def seed():
    db = SessionLocal()
    try:
        if db.query(models.Company).count() > 0:
            return

        comp = models.Company(name="ACME Corp")
        db.add(comp); db.flush()

        admin = models.User(company_id=comp.id, username="admin",
                            password_hash=auth.hash_password("admin123"),
                            is_admin=True)
        db.add(admin)

        loc = models.Location(company_id=comp.id, code="BLR-01",
                              name="Bengaluru HQ", rule_config=SAMPLE_RULE_CONFIG)
        db.add(loc); db.flush()

        # Holidays for Jan 2025
        for d, nm in [(date(2025, 1, 14), "Pongal"), (date(2025, 1, 26), "Republic Day")]:
            db.add(models.Holiday(location_id=loc.id, day=d, name=nm))

        employees = [
            models.Employee(location_id=loc.id, emp_code="E001", name="Asha Rao",
                            gender="F", joining_date=date(2024, 6, 1),
                            monthly_salary=45000, opening_leave=2.0),
            models.Employee(location_id=loc.id, emp_code="E002", name="Rahul Kumar",
                            gender="M", joining_date=date(2025, 1, 8),
                            monthly_salary=31000, opening_leave=0),
            models.Employee(location_id=loc.id, emp_code="E003", name="Priya Shah",
                            gender="F", joining_date=date(2023, 3, 1),
                            exit_date=date(2025, 1, 25),
                            monthly_salary=52000, opening_leave=3.5),
            models.Employee(location_id=loc.id, emp_code="E004", name="Vikram Singh",
                            gender="M", joining_date=date(2024, 11, 1),
                            monthly_salary=40000, opening_leave=1.0),
        ]
        for e in employees:
            db.add(e)
        db.flush()

        holiday_days = {date(2025, 1, 14), date(2025, 1, 26)}
        for e in employees:
            for d in range(1, 32):
                dt = date(2025, 1, d)
                if e.joining_date > dt:
                    continue
                if e.exit_date and e.exit_date < dt:
                    continue
                if dt in holiday_days:
                    code = "D"
                elif dt.weekday() == 6:
                    code = "C"
                else:
                    code = "A"
                # Tweaks to showcase flags
                if e.emp_code == "E004" and d in (15, 16):
                    code = "E"
                if e.emp_code == "E002" and d == 10:
                    code = "E"
                if e.emp_code == "E001" and d in (18, 20):
                    code = "E"
                db.add(models.AttendanceRecord(
                    employee_id=e.id, day=dt, code=code, worked_on_holiday=False,
                ))
        db.commit()

        # Export CSV alongside
        sample_dir = Path(__file__).parent.parent / "sample_data"
        sample_dir.mkdir(exist_ok=True)
        emp_by_id = {e.id: e for e in employees}
        rows = []
        for r in db.query(models.AttendanceRecord).all():
            if r.day.year == 2025 and r.day.month == 1:
                emp = emp_by_id.get(r.employee_id)
                if emp:
                    rows.append(f"{emp.emp_code},{r.day.isoformat()},{r.code},"
                                f"{1 if r.worked_on_holiday else 0}")
        (sample_dir / "attendance_jan_2025.csv").write_text(
            "emp_code,day,code,worked_on_holiday\n" + "\n".join(rows)
        )
    finally:
        db.close()
