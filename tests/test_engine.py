"""Unit tests covering each spec rule."""
from datetime import date, timedelta
from app.engine import calculate_payroll, DEFAULT_RULE_CONFIG


def _emp(**kw):
    base = dict(
        emp_code="E1", name="Test",
        gender="M",
        joining_date=date(2025, 1, 1),
        exit_date=None,
        monthly_salary=31000,
        opening_leave=0,
    )
    base.update(kw)
    return base


def _daily(year, month, mapping):
    """mapping: {day_int: (code, worked_on_holiday_bool?)}"""
    out = []
    for day, v in mapping.items():
        if isinstance(v, tuple):
            code, worked = v
        else:
            code, worked = v, False
        out.append({"day": date(year, month, day), "code": code, "worked_on_holiday": worked})
    return out


# ---------------------------------------------------------------------------
# Rule 1 — mid-week joiner gets week-off in 6-day / alt-Sat
# ---------------------------------------------------------------------------
def test_rule1_midweek_joiner_week_off_entitlement():
    # Jan 2025: employee joins Wed Jan 8; 6-day week, Sun off
    recs = []
    for day in range(8, 32):
        d = date(2025, 1, day)
        if d.weekday() == 6:
            recs.append({"day": d, "code": "C", "worked_on_holiday": False})
        else:
            recs.append({"day": d, "code": "A", "worked_on_holiday": False})
    result = calculate_payroll(
        employee=_emp(joining_date=date(2025, 1, 8)),
        year=2025, month=1, records=recs,
        rule_config={"week_pattern": "6day", "week_off_day": 6},
    )
    # Should recognise C days even though joined mid-week
    assert result["counts"]["C"] >= 3
    # No "excess" penalty — still approved
    assert result["approved_week_off_actual"] >= 3


# ---------------------------------------------------------------------------
# Rule 2 — mandatory approved leave is configurable; removed hardcoded 1.5
# ---------------------------------------------------------------------------
def test_rule2_approved_leave_is_config_driven():
    recs = _daily(2025, 1, {d: "A" for d in range(1, 32) if date(2025, 1, d).weekday() != 6})
    for d in range(1, 32):
        if date(2025, 1, d).weekday() == 6:
            recs.append({"day": date(2025, 1, d), "code": "C", "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(), year=2025, month=1, records=recs,
        rule_config={"approved_leaves_per_month": 3},
    )
    assert r["approved_leave"] == 3


# ---------------------------------------------------------------------------
# Rule 3 — females get one extra non-carry-forward leave
# ---------------------------------------------------------------------------
def test_rule3_female_extra_leave():
    recs = _daily(2025, 1, {d: "A" for d in range(1, 32)})
    male = calculate_payroll(employee=_emp(gender="M"), year=2025, month=1, records=recs,
                             rule_config={"approved_leaves_per_month": 1, "female_extra_leave": 1})
    female = calculate_payroll(employee=_emp(gender="F"), year=2025, month=1, records=recs,
                               rule_config={"approved_leaves_per_month": 1, "female_extra_leave": 1})
    assert female["approved_leave"] == male["approved_leave"] + 1


# ---------------------------------------------------------------------------
# Rule 4 — sandwich rule: leave-weekoff-leave => weekoff treated as leave
# ---------------------------------------------------------------------------
def test_rule4_sandwich_rule():
    # Sat Jan 4 = Leave, Sun Jan 5 = Week off, Mon Jan 6 = Leave
    recs = [
        {"day": date(2025, 1, 4), "code": "E", "worked_on_holiday": False},
        {"day": date(2025, 1, 5), "code": "C", "worked_on_holiday": False},
        {"day": date(2025, 1, 6), "code": "E", "worked_on_holiday": False},
    ]
    # fill rest as A
    for d in range(1, 32):
        if d in (4, 5, 6):
            continue
        dt = date(2025, 1, d)
        if dt.weekday() == 6:
            recs.append({"day": dt, "code": "C", "worked_on_holiday": False})
        else:
            recs.append({"day": dt, "code": "A", "worked_on_holiday": False})

    on = calculate_payroll(employee=_emp(), year=2025, month=1, records=recs,
                           rule_config={"sandwich_rule": True, "approved_leaves_per_month": 10,
                                        "excess_leave_to_absent": False})
    off = calculate_payroll(employee=_emp(), year=2025, month=1, records=recs,
                            rule_config={"sandwich_rule": False, "approved_leaves_per_month": 10,
                                         "excess_leave_to_absent": False})
    assert on["counts"]["E"] == off["counts"]["E"] + 1
    assert on["counts"]["C"] == off["counts"]["C"] - 1


# ---------------------------------------------------------------------------
# Rule 5 — exit-date trailing absence is unpaid
# ---------------------------------------------------------------------------
def test_rule5_exit_trailing_absence_unpaid():
    # Exit 27 Jan; worked up to 25; absent on 26 & 27
    recs = []
    for d in range(1, 28):
        dt = date(2025, 1, d)
        if dt.weekday() == 6:
            recs.append({"day": dt, "code": "C", "worked_on_holiday": False})
        elif d in (26, 27):
            recs.append({"day": dt, "code": "G", "worked_on_holiday": False})
        else:
            recs.append({"day": dt, "code": "A", "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(exit_date=date(2025, 1, 27)),
        year=2025, month=1, records=recs,
        rule_config={"exit_trailing_absence_unpaid": True},
    )
    assert r["effective_exit_date"] == "2025-01-25"
    # The absent days after exit should not appear in counts
    assert r["counts"]["G"] == 0


# ---------------------------------------------------------------------------
# Rule 6 — attendance starts on date of joining
# ---------------------------------------------------------------------------
def test_rule6_attendance_starts_on_join():
    recs = []
    for d in range(15, 32):
        dt = date(2025, 1, d)
        recs.append({"day": dt, "code": "A" if dt.weekday() != 6 else "C",
                     "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(joining_date=date(2025, 1, 15)),
        year=2025, month=1, records=recs,
        rule_config={"attendance_starts_on_join_date": True,
                     "approved_leaves_per_month": 0, "female_extra_leave": 0},
    )
    assert r["window"]["start"] == "2025-01-15"
    assert r["counts"]["G"] == 0  # Days 1-14 are not counted as absent


# ---------------------------------------------------------------------------
# Rule 7 — immediate leave after joining triggers flag
# ---------------------------------------------------------------------------
def test_rule7_immediate_leave_trigger():
    recs = [
        {"day": date(2025, 1, 1), "code": "A", "worked_on_holiday": False},
        {"day": date(2025, 1, 2), "code": "E", "worked_on_holiday": False},
    ]
    for d in range(3, 32):
        dt = date(2025, 1, d)
        recs.append({"day": dt, "code": "A" if dt.weekday() != 6 else "C",
                     "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(joining_date=date(2025, 1, 1)),
        year=2025, month=1, records=recs,
        rule_config={"triggers": {"immediate_leave_after_joining_days": 7,
                                  "consecutive_leave_days": 0},
                     "approved_leaves_per_month": 5},
    )
    assert any(f.startswith("IMMEDIATE_LEAVE_AFTER_JOINING") for f in r["flags"])


# ---------------------------------------------------------------------------
# Rule 8 — 2+ consecutive leave days triggers flag
# ---------------------------------------------------------------------------
def test_rule8_consecutive_leave_trigger():
    recs = []
    for d in range(1, 32):
        dt = date(2025, 1, d)
        code = "A" if dt.weekday() != 6 else "C"
        if d in (10, 11):
            code = "E"
        recs.append({"day": dt, "code": code, "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(), year=2025, month=1, records=recs,
        rule_config={"triggers": {"immediate_leave_after_joining_days": 0,
                                  "consecutive_leave_days": 2},
                     "approved_leaves_per_month": 5},
    )
    assert any(f.startswith("CONSECUTIVE_LEAVE") for f in r["flags"])


# ---------------------------------------------------------------------------
# Holiday-work multiplier (column J)
# ---------------------------------------------------------------------------
def test_holiday_work_multiplier():
    recs = []
    for d in range(1, 32):
        dt = date(2025, 1, d)
        if dt.weekday() == 6:  # Sunday worked
            recs.append({"day": dt, "code": "C", "worked_on_holiday": True})
        else:
            recs.append({"day": dt, "code": "A", "worked_on_holiday": False})
    r = calculate_payroll(
        employee=_emp(), year=2025, month=1, records=recs,
        rule_config={"holiday_work_multiplier": 2.0, "approved_leaves_per_month": 0,
                     "female_extra_leave": 0},
    )
    # Four Sundays in Jan 2025 (5,12,19,26) worked -> J = 4 * 2 = 8
    assert r["counts"]["J"] == 8


# ---------------------------------------------------------------------------
# Custom check formula
# ---------------------------------------------------------------------------
def test_custom_check_formula():
    recs = _daily(2025, 1, {d: ("A" if date(2025, 1, d).weekday() != 6 else "C")
                            for d in range(1, 32)})
    r = calculate_payroll(
        employee=_emp(opening_leave=2), year=2025, month=1, records=recs,
        rule_config={"checks": ["N + approved_leave - E == L",
                                "H == DM"]},
    )
    assert all(chk["pass"] for chk in r["checks"])


# ---------------------------------------------------------------------------
# Carry-forward variants
# ---------------------------------------------------------------------------
def test_rollover_vs_fixed():
    recs = _daily(2025, 1, {d: ("A" if date(2025, 1, d).weekday() != 6 else "C")
                            for d in range(1, 32)})
    fixed = calculate_payroll(employee=_emp(opening_leave=5), year=2025, month=1, records=recs,
                              rule_config={"leave_carry_forward": "fixed",
                                           "approved_leaves_per_month": 1.5,
                                           "female_extra_leave": 0})
    rollover = calculate_payroll(employee=_emp(opening_leave=5), year=2025, month=1, records=recs,
                                 rule_config={"leave_carry_forward": "rollover",
                                              "approved_leaves_per_month": 1.5,
                                              "female_extra_leave": 0})
    assert fixed["leave_ledger"]["L_closing"] == 1.5
    assert rollover["leave_ledger"]["L_closing"] == 6.5
