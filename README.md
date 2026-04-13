# Attendance Payroll Calculator

A configurable payroll calculation service that consumes daily attendance data
(from an external punching app) and computes monthly payable days per employee.

**All rules are per-company / per-location config** — no hardcoded policy.

## Quick start

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — the dashboard lets you:

1. Create a Company and Location with its rule config
2. Onboard employees (CSV or form)
3. Upload a month's attendance CSV
4. Run payroll → view dashboard + download CSV/Excel report

A sample company (`ACME`), location (`BLR-01`), employees, and attendance CSV
are seeded on first run — see `sample_data/`.

## Attendance codes

| Code | Meaning              |
|------|----------------------|
| A    | Present (Full Day)   |
| B    | Present (Half Day)   |
| C    | Week Off             |
| D    | Declared Holiday     |
| E    | Leave (Full Day)     |
| F    | Leave (Half Day)     |
| G    | Absent               |

## Configurable rules

Everything below is per-location JSON config; nothing is hardcoded.

- Week pattern: `5day` / `6day` / `alt_sat`
- `approved_leaves_per_month` (number, 0 to disable)
- `leave_carry_forward`: `fixed` | `rollover`
- `female_extra_leave` (number, 0 to disable; non-carry-forward)
- `holiday_work_multiplier` (e.g. 2.0 → working on C/D pays double)
- `sandwich_rule` (bool) — leave–weekoff–leave ⇒ weekoff counted as leave
- `exit_trailing_absence_unpaid` (bool) — trailing absences after last attended day ⇒ unpaid + exit date moved
- `attendance_starts_on_join_date` (bool)
- `excess_leave_to_absent` (bool) — leaves beyond approved bucket convert to G
- `triggers`:
  - `immediate_leave_after_joining_days` (int; flag if E/F within N days of joining)
  - `consecutive_leave_days` (int; flag if ≥ N consecutive E/F)
- `checks`: list of formula checks, e.g.
  `"N - E + approved_leave == L"`

## Payroll formulas

- `H = A + B + C + D + E + F + G` (total days in period)
- `I = A + B + J + D(*) + E(*) + F(*)` (payable days)
  - `J` = days where C/D was worked, multiplied per `holiday_work_multiplier`
  - `D` converted to `G` if it falls between leave days and `sandwich_rule` is on
  - `E/F` beyond `approved_leaves` convert to `G` if `excess_leave_to_absent`
- `Approved week off used = (A + B) / 7`
- Closing leave `L = N - E + approved_leave` (rollover); `= approved_leave` (fixed)

## API

- `POST /api/companies` / `GET /api/companies`
- `POST /api/locations` / `GET /api/locations`
- `POST /api/employees` / `GET /api/employees`
- `POST /api/attendance/upload` (multipart CSV)
- `POST /api/payroll/run` `{location_id, month, year}`
- `GET  /api/payroll/report?run_id=…&format=csv|xlsx`

## Tests

```bash
pytest
```
