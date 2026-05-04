"""
Payroll calculation engine.

Pure-python, no DB dependency. Takes:
  - employee dict
  - list of (date, code, worked_on_holiday) attendance records for the month
  - rule_config (per-location JSON)

Returns a dict with all calculated fields (H, I, J, K, L, triggers, check results).

Nothing is hardcoded — all policies come from rule_config.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


DEFAULT_RULE_CONFIG: dict[str, Any] = {
    "week_pattern": "6day",
    "week_off_day": 6,
    "alt_sat_off_weeks": [2, 4],
    "roster_mode": False,

    "week_off_cap_percent": 0,

    "approved_leaves_per_month": 0,
    "leave_carry_forward": "rollover",
    "female_extra_leave": 0,
    "excess_leave_to_absent": True,

    "holiday_work_multiplier": 2.0,
    "sandwich_rule": True,

    "min_working_days": 0,

    "exit_trailing_absence_unpaid": True,
    "attendance_starts_on_join_date": True,

    "triggers": {
        "immediate_leave_after_joining_days": 7,
        "consecutive_leave_days": 2,
    },

    "checks": [
        "N - E + approved_leave == L",
    ],

    "vendor_code_map": {
        "P": "A",
        "HD": "B",
        "WO": "C",
        "H": "D",
        "L": "E",
        "HL": "F",
        "A": "G",
    },
}


def _merge(base: dict, override: dict | None) -> dict:
    out = {**base}
    if not override:
        return out
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def _week_of_month(d: date) -> int:
    first = d.replace(day=1)
    offset = (first.weekday()) % 7
    return ((d.day + offset - 1) // 7) + 1


def _is_scheduled_week_off(d: date, cfg: dict, emp_week_off_day: int | None = None) -> bool:
    pattern = cfg["week_pattern"]
    wd = d.weekday()
    if pattern == "roster" or cfg.get("roster_mode"):
        return emp_week_off_day is not None and wd == int(emp_week_off_day)
    if pattern == "5day":
        return wd in (5, 6)
    if pattern == "6day":
        return wd == cfg["week_off_day"]
    if pattern == "alt_sat":
        if wd == 6:
            return True
        if wd == 5:
            return _week_of_month(d) in cfg["alt_sat_off_weeks"]
        return False
    return False


@dataclass
class Counts:
    A: float = 0.0
    B: float = 0.0
    C: float = 0.0
    D: float = 0.0
    E: float = 0.0
    F: float = 0.0
    G: float = 0.0
    J: float = 0.0

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in "ABCDEFGJ"}


def _count_from_norm(day_list: list[date], norm: dict, cfg: dict) -> Counts:
    c = Counts()
    for d in day_list:
        code = norm[d]["code"]
        worked = norm[d].get("worked_on_holiday", False)
        if code == "A":
            c.A += 1
        elif code == "B":
            c.B += 0.5
        elif code == "C":
            c.C += 1
            if worked:
                c.J += cfg["holiday_work_multiplier"]
        elif code == "D":
            c.D += 1
            if worked:
                c.J += cfg["holiday_work_multiplier"]
        elif code == "E":
            c.E += 1
        elif code == "F":
            c.F += 0.5
        elif code == "G":
            c.G += 1
    return c


def calculate_payroll(
    *,
    employee: dict,
    year: int,
    month: int,
    records: list[dict],
    rule_config: dict | None = None,
) -> dict:
    cfg = _merge(DEFAULT_RULE_CONFIG, rule_config)
    flags: list[str] = []
    notes: list[str] = []

    dm = monthrange(year, month)[1]
    last_day = date(year, month, dm)
    first_day = date(year, month, 1)

    joining = employee["joining_date"]
    exit_d = employee.get("exit_date")

    window_start = first_day
    window_end = last_day
    if cfg["attendance_starts_on_join_date"] and joining and joining > first_day and joining <= last_day:
        window_start = joining
    if exit_d and first_day <= exit_d <= last_day:
        window_end = exit_d

    by_day: dict[date, dict] = {r["day"]: r for r in records}

    # ---- Exit trailing-absence rule ----
    effective_exit = exit_d
    if cfg["exit_trailing_absence_unpaid"] and exit_d and first_day <= exit_d <= last_day:
        cur = exit_d
        last_attended = None
        while cur >= window_start:
            rec = by_day.get(cur)
            if rec and rec["code"] in ("A", "B"):
                last_attended = cur
                break
            cur -= timedelta(days=1)
        if last_attended and last_attended < exit_d:
            notes.append(
                f"Exit trailing absence: exit moved from {exit_d} to {last_attended}"
            )
            effective_exit = last_attended
            window_end = last_attended

    # ---- Build day list ----
    day_list: list[date] = []
    d = window_start
    while d <= window_end:
        day_list.append(d)
        d += timedelta(days=1)

    # Normalize: ensure every day has a record
    emp_wo = employee.get("week_off_day")
    norm: dict[date, dict] = {}
    for d in day_list:
        r = by_day.get(d)
        if r:
            norm[d] = dict(r)
        else:
            if _is_scheduled_week_off(d, cfg, emp_wo):
                norm[d] = {"day": d, "code": "C", "worked_on_holiday": False}
            else:
                norm[d] = {"day": d, "code": "G", "worked_on_holiday": False}

    # Save original codes before any rule application
    original_codes = {d: norm[d]["code"] for d in day_list}

    # ---- Sandwich rule ----
    if cfg["sandwich_rule"]:
        for i, d in enumerate(day_list):
            code = norm[d]["code"]
            if code not in ("C", "D"):
                continue
            prev_code = None
            for j in range(i - 1, -1, -1):
                pc = norm[day_list[j]]["code"]
                if pc not in ("C", "D"):
                    prev_code = pc
                    break
            next_code = None
            for j in range(i + 1, len(day_list)):
                nc = norm[day_list[j]]["code"]
                if nc not in ("C", "D"):
                    next_code = nc
                    break
            if prev_code in ("E", "F") and next_code in ("E", "F"):
                norm[d]["code"] = "E"
                norm[d]["_sandwich"] = True
                norm[d]["_reason"] = f"Sandwich rule: {code}→E (leave on both sides)"

    # ---- Approved leave bucket ----
    approved_leave = float(cfg["approved_leaves_per_month"])
    if employee.get("gender", "M").upper() == "F":
        approved_leave += float(cfg["female_extra_leave"])
    leave_bucket = approved_leave
    if cfg["leave_carry_forward"] == "rollover":
        leave_bucket += float(employee.get("opening_leave", 0) or 0)

    # ---- Count leaves to determine excess ----
    leave_e = sum(1 for d in day_list if norm[d]["code"] == "E")
    leave_f = sum(0.5 for d in day_list if norm[d]["code"] == "F")
    leave_taken = leave_e + leave_f
    excess = max(0.0, leave_taken - leave_bucket)

    # ---- Excess leave → absent (modify specific days in norm) ----
    if cfg["excess_leave_to_absent"] and excess > 0:
        remaining = excess
        for d in reversed(day_list):
            if remaining <= 0:
                break
            if norm[d]["code"] == "E" and not norm[d].get("_sandwich"):
                norm[d]["code"] = "G"
                norm[d]["_reason"] = f"Excess leave→Absent (beyond {leave_bucket} approved)"
                remaining -= 1
        for d in reversed(day_list):
            if remaining <= 0:
                break
            if norm[d]["code"] == "F":
                norm[d]["code"] = "G"
                norm[d]["_reason"] = f"Excess half-leave→Absent (beyond {leave_bucket} approved)"
                remaining -= 0.5
        notes.append(f"{excess} day(s) excess leave converted to Absent")

    # ---- Week-off cap % ----
    worked_days_for_info = sum(1 for d in day_list if norm[d]["code"] == "A") + \
                           sum(0.5 for d in day_list if norm[d]["code"] == "B")
    roster = bool(cfg.get("roster_mode")) or cfg["week_pattern"] == "roster"
    if roster:
        approved_week_off = None
    else:
        per_week = {"5day": 5, "6day": 6, "alt_sat": 5.5}.get(cfg["week_pattern"], 6)
        approved_week_off = round(worked_days_for_info / per_week, 2) if per_week else 0

    wo_count = sum(1 for d in day_list if norm[d]["code"] == "C")
    approved_week_off_actual = wo_count
    excess_week_off = 0.0

    cap_pct = float(cfg.get("week_off_cap_percent", 0) or 0)
    if cap_pct > 0:
        base_days = float(len(day_list))
        cap_allowed = round(base_days * cap_pct / 100.0, 2)
        if wo_count > cap_allowed:
            excess_wo = wo_count - cap_allowed
            excess_week_off = excess_wo
            remaining = excess_wo
            for d in reversed(day_list):
                if remaining <= 0:
                    break
                if norm[d]["code"] == "C" and not norm[d].get("worked_on_holiday"):
                    norm[d]["code"] = "G"
                    norm[d]["_reason"] = f"Week-off cap: exceeded {cap_pct}% cap ({cap_allowed:.1f}/{base_days:.0f} days)"
                    remaining -= 1
            notes.append(
                f"Week-off cap: {excess_wo} day(s) exceeded "
                f"{cap_pct}% cap ({cap_allowed:.2f} of {base_days:.0f} days) "
                "— converted to Absent"
            )

    # ---- Final count from norm (after all rule modifications) ----
    c = _count_from_norm(day_list, norm, cfg)

    # ---- Totals ----
    H = c.A + c.B + c.C + c.D + c.E + c.F + c.G
    I = c.A + c.B + c.J + c.D + c.E + c.F

    # ---- Triggers ----
    trig = cfg.get("triggers", {}) or {}
    imm_window = int(trig.get("immediate_leave_after_joining_days", 0) or 0)
    if imm_window > 0 and joining:
        for d in day_list:
            if d <= joining + timedelta(days=imm_window) and norm[d]["code"] in ("E", "F"):
                flags.append(f"IMMEDIATE_LEAVE_AFTER_JOINING:{d.isoformat()}")
                break

    streak_threshold = int(trig.get("consecutive_leave_days", 0) or 0)
    if streak_threshold > 0:
        streak = 0
        streak_start = None
        for d in day_list:
            if norm[d]["code"] in ("E", "F"):
                if streak == 0:
                    streak_start = d
                streak += 1
                if streak >= streak_threshold:
                    flags.append(
                        f"CONSECUTIVE_LEAVE:{streak_start.isoformat()}+{streak}"
                    )
                    break
            else:
                streak = 0
                streak_start = None

    # ---- Consecutive absence detection (for flags) ----
    abs_streak = 0
    abs_start = None
    for d in day_list:
        if norm[d]["code"] == "G":
            if abs_streak == 0:
                abs_start = d
            abs_streak += 1
            if abs_streak >= 3:
                flags.append(f"CONSECUTIVE_ABSENCE:{abs_start.isoformat()}+{abs_streak}")
                break
        else:
            abs_streak = 0
            abs_start = None

    # ---- Leave ledger ----
    N = float(employee.get("opening_leave", 0) or 0)
    if cfg["leave_carry_forward"] == "fixed":
        L = approved_leave
        M_next = approved_leave
    else:
        L = N + approved_leave - c.E - c.F
        M_next = L

    # ---- Custom formula checks ----
    check_results = []
    ctx = {
        **c.as_dict(),
        "H": H, "I": I, "N": N, "L": L, "M": M_next,
        "approved_leave": approved_leave,
        "leave_bucket": leave_bucket,
        "DM": dm, "LD": dm,
    }
    for expr in cfg.get("checks", []) or []:
        try:
            ok = bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307
            check_results.append({"expr": expr, "pass": ok})
        except Exception as ex:
            check_results.append({"expr": expr, "pass": False, "error": str(ex)})

    # ---- Payroll amount ----
    salary = float(employee.get("monthly_salary", 0) or 0)
    per_day = salary / dm if dm else 0
    payable_days = I
    gross = round(per_day * payable_days, 2)

    # ---- Min working days rule ----
    min_wd = int(cfg.get("min_working_days", 0) or 0)
    worked_days_actual = c.A + c.B
    min_working_days_applied = False
    if min_wd > 0 and worked_days_actual < min_wd:
        notes.append(
            f"Min working days: worked {worked_days_actual} < required {min_wd} — gross set to 0"
        )
        flags.append(f"MIN_WORKING_DAYS:{worked_days_actual}/{min_wd}")
        gross = 0
        min_working_days_applied = True

    # ---- Build day_details (per-day original vs final + reason) ----
    day_details = []
    for d in day_list:
        orig = original_codes[d]
        final = norm[d]["code"]
        reason = norm[d].get("_reason", "")
        day_details.append({
            "day": d.isoformat(),
            "original": orig,
            "final": final,
            "changed": orig != final,
            "reason": reason,
        })

    return {
        "employee": {k: employee.get(k) for k in ("emp_code", "title", "name", "gender")},
        "period": {"year": year, "month": month, "DM": dm, "LD": dm},
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "effective_exit_date": effective_exit.isoformat() if effective_exit else None,
        "counts": c.as_dict(),
        "H_total_days": H,
        "I_payable_days": round(I, 2),
        "approved_leave": approved_leave,
        "leave_bucket": leave_bucket,
        "approved_week_off_earned": approved_week_off,
        "approved_week_off_actual": approved_week_off_actual,
        "excess_week_off": excess_week_off,
        "leave_ledger": {"N_opening": N, "E_taken": c.E, "F_taken": c.F,
                         "L_closing": round(L, 2), "M_next_opening": round(M_next, 2)},
        "salary": {"monthly": salary, "per_day": round(per_day, 2), "gross_payable": gross},
        "min_working_days_applied": min_working_days_applied,
        "day_details": day_details,
        "flags": flags,
        "notes": notes,
        "checks": check_results,
        "rule_config_used": cfg,
    }
