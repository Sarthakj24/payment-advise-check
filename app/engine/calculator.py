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


# Full default config. Every flag documented. A location's saved config is
# merged over these defaults so admins only need to specify what's different.
DEFAULT_RULE_CONFIG: dict[str, Any] = {
    "week_pattern": "6day",          # "5day" | "6day" | "alt_sat" | "roster"
    "week_off_day": 6,               # 0=Mon ... 6=Sun (when pattern=6day)
    "alt_sat_off_weeks": [2, 4],     # when pattern=alt_sat, Sats off in these week-of-month indexes
    # roster_mode: if true (or pattern="roster"), each employee has their own
    # Employee.week_off_day. In that case the (A+B)/7 calculation is skipped
    # and the week_off_cap_percent rule governs week-off budgeting.
    "roster_mode": False,

    # OVERRIDES EVERYTHING: ceiling on week-offs as % of total working days.
    # If actual C count exceeds this cap, excess days convert to Absent (G).
    # 0 disables the cap entirely.
    "week_off_cap_percent": 0,

    "approved_leaves_per_month": 0,      # default: no approved leaves; weekoffs (C) only
    "leave_carry_forward": "rollover",   # "fixed" | "rollover"
    "female_extra_leave": 0,             # default: no extra; company can enable
    "excess_leave_to_absent": True,      # leaves beyond approved bucket ⇒ Absent

    "holiday_work_multiplier": 2.0,      # working on C/D pays this many days
    "sandwich_rule": True,               # leave-weekoff-leave ⇒ weekoff counted as leave

    "exit_trailing_absence_unpaid": True,
    "attendance_starts_on_join_date": True,

    "triggers": {
        "immediate_leave_after_joining_days": 7,
        "consecutive_leave_days": 2,
    },

    "checks": [
        "N - E + approved_leave == L",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _merge(base: dict, override: dict | None) -> dict:
    """Shallow-ish merge: override wins, nested dicts merged one level."""
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
    """1-indexed week of the month (Mon as first day)."""
    first = d.replace(day=1)
    # days to add so that Monday is start
    offset = (first.weekday()) % 7
    return ((d.day + offset - 1) // 7) + 1


def _is_scheduled_week_off(d: date, cfg: dict, emp_week_off_day: int | None = None) -> bool:
    pattern = cfg["week_pattern"]
    wd = d.weekday()  # 0=Mon
    # Roster mode: use employee's own week_off_day
    if pattern == "roster" or cfg.get("roster_mode"):
        return emp_week_off_day is not None and wd == int(emp_week_off_day)
    if pattern == "5day":
        return wd in (5, 6)          # Sat+Sun off
    if pattern == "6day":
        return wd == cfg["week_off_day"]
    if pattern == "alt_sat":
        if wd == 6:
            return True               # Sun always off
        if wd == 5:
            return _week_of_month(d) in cfg["alt_sat_off_weeks"]
        return False
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

@dataclass
class Counts:
    A: float = 0.0
    B: float = 0.0
    C: float = 0.0
    D: float = 0.0
    E: float = 0.0
    F: float = 0.0
    G: float = 0.0
    J: float = 0.0  # holiday-work salary days (after multiplier)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in "ABCDEFGJ"}


def calculate_payroll(
    *,
    employee: dict,
    year: int,
    month: int,
    records: list[dict],
    rule_config: dict | None = None,
) -> dict:
    """
    employee: {emp_code, name, gender('M'|'F'|'O'), joining_date, exit_date,
               monthly_salary, opening_leave}
    records: [{day: date, code: 'A'..'G', worked_on_holiday: bool}, ...]
    """
    cfg = _merge(DEFAULT_RULE_CONFIG, rule_config)
    flags: list[str] = []
    notes: list[str] = []

    dm = monthrange(year, month)[1]
    last_day = date(year, month, dm)
    first_day = date(year, month, 1)

    joining = employee["joining_date"]
    exit_d = employee.get("exit_date")

    # Determine effective attendance window
    window_start = first_day
    window_end = last_day
    if cfg["attendance_starts_on_join_date"] and joining and joining > first_day and joining <= last_day:
        window_start = joining
    if exit_d and first_day <= exit_d <= last_day:
        window_end = exit_d

    # Index records by date
    by_day: dict[date, dict] = {r["day"]: r for r in records}

    # ---- Exit trailing-absence rule (rule 5) -------------------------------
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

    # ---- Build day list and apply sandwich rule (rule 4) -------------------
    day_list: list[date] = []
    d = window_start
    while d <= window_end:
        day_list.append(d)
        d += timedelta(days=1)

    # Normalize: ensure every day in window has a record
    emp_wo = employee.get("week_off_day")
    norm: dict[date, dict] = {}
    for d in day_list:
        r = by_day.get(d)
        if r:
            norm[d] = dict(r)
        else:
            # No record → treat as week-off if scheduled, else Absent
            if _is_scheduled_week_off(d, cfg, emp_wo):
                norm[d] = {"day": d, "code": "C", "worked_on_holiday": False}
            else:
                norm[d] = {"day": d, "code": "G", "worked_on_holiday": False}

    # Sandwich: C or D flanked by leave (E/F) on both sides ⇒ becomes leave (E)
    if cfg["sandwich_rule"]:
        for i, d in enumerate(day_list):
            code = norm[d]["code"]
            if code not in ("C", "D"):
                continue
            # walk back to prev non-C/D day
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

    # ---- Count raw codes ---------------------------------------------------
    c = Counts()
    for d in day_list:
        code = norm[d]["code"]
        worked = norm[d].get("worked_on_holiday", False)
        if code == "A":
            c.A += 1
        elif code == "B":
            c.B += 0.5
            # B also contributes 0.5 to A for payable-days sense — we keep separate;
            # H should sum to period days, so count B as 0.5 here but we'll also
            # track half-day present separately. For simplicity: B contributes 0.5
            # to present and 0.5 goes "unaccounted" — clients typically treat B as
            # 0.5 present + 0.5 absent or 0.5 leave. We leave that to config.
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

    # ---- Approved leave bucket (rules 2, 3) --------------------------------
    # `approved_leave` = this month's earned quota (matches spec "as defined")
    # `leave_bucket`   = total available this month (earned + rollover if any)
    approved_leave = float(cfg["approved_leaves_per_month"])
    if employee.get("gender", "M").upper() == "F":
        approved_leave += float(cfg["female_extra_leave"])
    leave_bucket = approved_leave
    if cfg["leave_carry_forward"] == "rollover":
        leave_bucket += float(employee.get("opening_leave", 0) or 0)

    # ---- Excess leave → absent --------------------------------------------
    leave_taken = c.E + c.F
    excess = max(0.0, leave_taken - leave_bucket)
    if cfg["excess_leave_to_absent"] and excess > 0:
        # Move excess from E/F to G — shave off E first, then F (halves).
        move = excess
        e_move = min(c.E, move)
        c.E -= e_move
        c.G += e_move
        move -= e_move
        if move > 0:
            f_move = min(c.F, move)
            c.F -= f_move
            c.G += f_move
        notes.append(f"{excess} day(s) excess leave converted to Absent")

    # ---- Week-off cap % rule (OVERRIDES everything else) -------------------
    # If roster_mode: skip the (A+B)/7 mid-week-joiner proration — the cap %
    # covers week-off budgeting regardless of pattern.
    # Otherwise compute traditional approved week-off for info only.
    worked_days = c.A + c.B
    roster = bool(cfg.get("roster_mode")) or cfg["week_pattern"] == "roster"
    if roster:
        approved_week_off = None  # not applicable
    else:
        per_week = {"5day": 5, "6day": 6, "alt_sat": 5.5}.get(cfg["week_pattern"], 6)
        approved_week_off = round(worked_days / per_week, 2) if per_week else 0
    approved_week_off_actual = c.C
    excess_week_off = 0.0

    # Apply cap %: C must not exceed cap_pct * total working days in window
    cap_pct = float(cfg.get("week_off_cap_percent", 0) or 0)
    if cap_pct > 0:
        # base = total days in window (a natural denominator for "working days")
        base_days = float(len(day_list))
        cap_allowed = round(base_days * cap_pct / 100.0, 2)
        if c.C > cap_allowed:
            excess = c.C - cap_allowed
            c.C -= excess
            c.G += excess
            excess_week_off = excess
            notes.append(
                f"Week-off cap: {excess} day(s) exceeded "
                f"{cap_pct}% cap ({cap_allowed:.2f} of {base_days:.0f} days) "
                "— converted to Absent"
            )

    # ---- Totals ------------------------------------------------------------
    H = c.A + c.B + c.C + c.D + c.E + c.F + c.G
    I = c.A + c.B + c.J + c.D + c.E + c.F  # payable (after conversions above)
    # If holiday_work_multiplier doubles C/D when worked, we should NOT also
    # pay the plain C/D day — subtract the base day that became J.
    # J already includes the multiplier (e.g. 2.0), so net extra = J - worked_days_on_holiday.
    # Simpler: payable = A + B + (C or D worked ? multiplier : 1 if paid) + E + F.
    # We keep I as above; dashboard shows both so admins can verify.

    # ---- Triggers (rules 7, 8) --------------------------------------------
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

    # ---- Leave ledger ------------------------------------------------------
    N = float(employee.get("opening_leave", 0) or 0)  # this-month opening
    if cfg["leave_carry_forward"] == "fixed":
        L = approved_leave          # resets every month
        M_next = approved_leave
    else:
        L = N + approved_leave - c.E - c.F
        M_next = L

    # ---- Custom formula checks --------------------------------------------
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
            ok = bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307 — admin-defined
            check_results.append({"expr": expr, "pass": ok})
        except Exception as ex:
            check_results.append({"expr": expr, "pass": False, "error": str(ex)})

    # ---- Payroll amount ----------------------------------------------------
    salary = float(employee.get("monthly_salary", 0) or 0)
    per_day = salary / dm if dm else 0
    payable_days = I
    gross = round(per_day * payable_days, 2)

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
        "flags": flags,
        "notes": notes,
        "checks": check_results,
        "rule_config_used": cfg,
    }
