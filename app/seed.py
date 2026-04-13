"""Seed a sample tenant, location, 20 employees, holidays, and attendance
covering every documented rule. Runs once on startup when DB is empty."""
from datetime import date
from pathlib import Path
from .db import SessionLocal
from . import models, auth


# Only weekoffs (C) are approved by default. Any leave (E/F) counts as absent
# unless the company configures approved_leaves_per_month > 0.
SAMPLE_RULE_CONFIG = {
    "week_pattern": "6day",
    "week_off_day": 6,                          # Sunday off
    "approved_leaves_per_month": 0,
    "leave_carry_forward": "rollover",
    "female_extra_leave": 0,
    "excess_leave_to_absent": True,
    "holiday_work_multiplier": 2.0,
    "sandwich_rule": True,
    "exit_trailing_absence_unpaid": True,
    "attendance_starts_on_join_date": True,
    "triggers": {
        "immediate_leave_after_joining_days": 7,
        "consecutive_leave_days": 2,
    },
    "checks": ["H == DM", "I <= DM + 2"],
}


# ----- 20-employee spec covering every rule --------------------------------
# Each entry: (code, title, name, gender, joining, exit, salary, opening_leave, overrides)
# overrides: {day_int: code, or day_int: (code, worked_on_holiday)}
EMPLOYEE_PLAN = [
    ("E001", "Ms",  "Anita — Perfect Attendance",     "F", (2024, 1,  1), None,           30000, 0.0, {}),
    ("E002", "Mr",  "Bhuvan — Mid-week Joiner",       "M", (2025, 1,  8), None,           31000, 0.0, {}),
    ("E003", "Mr",  "Chirag — Exit Mid-month Clean",  "M", (2024, 1,  1), (2025, 1, 15),  48000, 0.0, {}),
    ("E004", "Ms",  "Deepa — Joined Last Day",        "F", (2025, 1, 31), None,           40000, 0.0, {}),
    ("E005", "Mrs", "Esha — Exit 27, Absent 25 & 27", "F", (2023, 3,  1), (2025, 1, 27),  52000, 3.5,
     {25: "G", 27: "G"}),
    ("E006", "Mr",  "Farhan — Joined Mid-month",      "M", (2025, 1, 13), None,           33000, 0.0, {}),
    ("E007", "Mr",  "Gaurav — Immediate Leave",       "M", (2025, 1,  6), None,           32000, 0.0,
     {7: "E"}),
    ("E008", "Ms",  "Harini — Consecutive Leaves",    "F", (2024, 6,  1), None,           34000, 0.0,
     {14: "E", 15: "E"}),
    ("E009", "Mr",  "Ishaan — Sandwich (Sat/Sun/Mon)","M", (2024, 1,  1), None,           36000, 0.0,
     {18: "E", 20: "E"}),
    ("E010", "Mrs", "Jaya — Worked on Pongal",        "F", (2024, 1,  1), None,           37000, 0.0,
     {14: ("D", True)}),
    ("E011", "Mr",  "Kiran — Worked Sunday",          "M", (2024, 1,  1), None,           38000, 0.0,
     {12: ("C", True)}),
    ("E012", "Ms",  "Lata — Half-day Present",        "F", (2024, 1,  1), None,           39000, 0.0,
     {10: "B"}),
    ("E013", "Mr",  "Manoj — Half-day Leave",         "M", (2024, 1,  1), None,           41000, 0.0,
     {21: "F"}),
    ("E014", "Ms",  "Neha — Multiple Leaves (all G)", "F", (2024, 1,  1), None,           42000, 0.0,
     {6: "E", 13: "E", 20: "E"}),
    ("E015", "Mr",  "Omar — Opening Leave 5.0",       "M", (2023, 1,  1), None,           46000, 5.0, {}),
    ("E016", "Ms",  "Priya — Full Month Absent",      "F", (2024, 1,  1), None,           20000, 0.0,
     {d: "G" for d in range(1, 32) if date(2025, 1, d).weekday() != 6 and d not in (14, 26)}),
    ("E017", "Mr",  "Qasim — Absent Streak 15-20",    "M", (2024, 1,  1), None,           28000, 0.0,
     {15: "G", 16: "G", 17: "G", 18: "G", 20: "G"}),
    ("E018", "Ms",  "Riya — Joined 6 Exited 20",      "F", (2025, 1,  6), (2025, 1, 20),  41000, 0.0, {}),
    ("E019", "Mr",  "Saurabh — Late Join + Leave",    "M", (2025, 1, 20), None,           30000, 0.0,
     {22: "E"}),
    ("E020", "Ms",  "Tanvi — All Rules Combined",     "F", (2025, 1, 13), None,           50000, 0.0,
     {26: ("D", True), 28: "E", 29: "E"}),
]


def seed():
    db = SessionLocal()
    try:
        if db.query(models.Company).count() > 0:
            return

        comp = models.Company(name="ACME Corp")
        db.add(comp); db.flush()

        db.add(models.User(company_id=comp.id, email="admin@acme.test",
                           password_hash=auth.hash_password("admin123"),
                           role="admin", is_admin=True))
        db.add(models.User(company_id=comp.id, email="kam@acme.test",
                           password_hash=auth.hash_password("kam123"),
                           role="kam", is_admin=False))

        loc = models.Location(company_id=comp.id, code="BLR-01",
                              name="Bengaluru HQ", rule_config=SAMPLE_RULE_CONFIG)
        db.add(loc); db.flush()

        # Holidays: Pongal + Republic Day
        HOLIDAYS = {date(2025, 1, 14): "Pongal", date(2025, 1, 26): "Republic Day"}
        for d, nm in HOLIDAYS.items():
            db.add(models.Holiday(location_id=loc.id, day=d, name=nm))

        employees = []
        for (code, title, name, gender, jd, ed, salary, opening, overrides) in EMPLOYEE_PLAN:
            e = models.Employee(
                location_id=loc.id, emp_code=code, title=title, name=name, gender=gender,
                joining_date=date(*jd),
                exit_date=date(*ed) if ed else None,
                monthly_salary=salary, opening_leave=opening,
            )
            db.add(e); employees.append((e, overrides))
        db.flush()

        # Generate attendance
        for (e, overrides) in employees:
            for d in range(1, 32):
                dt = date(2025, 1, d)
                if dt < e.joining_date:
                    continue
                if e.exit_date and dt > e.exit_date:
                    continue

                # Default code
                if dt in HOLIDAYS:
                    code, worked = "D", False
                elif dt.weekday() == 6:
                    code, worked = "C", False
                else:
                    code, worked = "A", False

                # Apply override (may be "E" or ("D", True) etc.)
                ov = overrides.get(d)
                if isinstance(ov, tuple):
                    code, worked = ov[0], ov[1]
                elif isinstance(ov, str):
                    code = ov

                db.add(models.AttendanceRecord(
                    employee_id=e.id, day=dt, code=code, worked_on_holiday=worked,
                ))
        db.commit()

        # Export CSV for reference
        sample_dir = Path(__file__).parent.parent / "sample_data"
        sample_dir.mkdir(exist_ok=True)
        emp_by_id = {e.id: e for (e, _) in employees}
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
