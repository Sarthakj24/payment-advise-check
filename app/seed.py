"""Seed a sample company, location, employees, and attendance for demo."""
from datetime import date, timedelta
from pathlib import Path
from .db import SessionLocal
from . import models


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

        loc = models.Location(company_id=comp.id, code="BLR-01",
                              name="Bengaluru HQ", rule_config=SAMPLE_RULE_CONFIG)
        db.add(loc); db.flush()

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

        # Generate Jan-2025 attendance
        for e in employees:
            for d in range(1, 32):
                dt = date(2025, 1, d)
                if e.joining_date > dt:
                    continue
                if e.exit_date and e.exit_date < dt and e.emp_code != "E003":
                    continue

                if dt.weekday() == 6:
                    code = "C"; worked = False
                else:
                    code = "A"; worked = False

                # Vikram takes 2 consecutive leaves
                if e.emp_code == "E004" and d in (14, 15):
                    code = "E"
                # Rahul takes immediate leave after joining
                if e.emp_code == "E002" and d == 10:
                    code = "E"
                # Priya — exit 25; trailing absence on 26, 27
                if e.emp_code == "E003" and d in (26, 27):
                    code = "G"
                # Asha — sandwich example: Sat leave, Sun off, Mon leave (18/19/20)
                if e.emp_code == "E001" and d in (18, 20):
                    code = "E"

                db.add(models.AttendanceRecord(
                    employee_id=e.id, day=dt, code=code,
                    worked_on_holiday=worked,
                ))
        db.commit()

        # Also write sample CSV for reference
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
