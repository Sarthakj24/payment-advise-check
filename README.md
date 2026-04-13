# Attendance Payroll Calculator

Configurable payroll calculator. Consumes daily attendance, applies a
per-location rule engine, and produces monthly payable days + payroll.

**Every policy is configurable per company/location** — nothing is hardcoded.

---

## Try it (30 seconds)

Requires Python 3.11+.

```bash
git clone <this-repo>
cd Test
git checkout claude/app-from-excel-spec-6rHnC
./run.sh
```

Open http://127.0.0.1:8000 — sign in with the preloaded demo account:

- Username: `admin`
- Password: `admin123`
- Company: ACME Corp · Location: Bengaluru HQ · 4 sample employees · January 2025 attendance prefilled

Click **"Register company"** on the login page to create your own tenant and start fresh.

### Alternative: Docker

```bash
docker build -t payroll .
docker run -p 8000:8000 payroll
```

---

## Tabs in the UI

| Tab           | What it does                                                                |
|---------------|-----------------------------------------------------------------------------|
| Run Payroll   | Pick location + month → calculates; download CSV/Excel                      |
| Attendance    | Monthly grid (cells prefilled from week pattern + holidays); edit & save    |
| Employees     | Add / edit / delete employees (per location)                                |
| Locations     | Add / edit / delete locations, with full rule-config JSON                    |
| Holidays      | Manage per-location holiday calendar; holidays auto-appear as "D" in grid  |
| Rule Config   | Shortcut to edit just the rule JSON for a location                          |
| Upload CSV    | Bulk attendance upload — `emp_code,day,code,worked_on_holiday`              |

---

## Attendance codes

| Code | Meaning            |
|------|--------------------|
| A    | Present (Full Day) |
| B    | Present (Half Day) |
| C    | Week Off           |
| D    | Declared Holiday   |
| E    | Leave (Full Day)   |
| F    | Leave (Half Day)   |
| G    | Absent             |

A `worked_on_holiday` flag can be set on C/D days to pay the
`holiday_work_multiplier`.

---

## Configurable rules (per location)

```jsonc
{
  "week_pattern": "6day",            // "5day" | "6day" | "alt_sat"
  "week_off_day": 6,                 // 0=Mon…6=Sun
  "alt_sat_off_weeks": [2, 4],       // when alt_sat: which Sats are off

  "approved_leaves_per_month": 1.5,  // any number; 0 disables
  "leave_carry_forward": "rollover", // "fixed" | "rollover"
  "female_extra_leave": 1,           // non-carry-forward
  "excess_leave_to_absent": true,

  "holiday_work_multiplier": 2.0,    // working on C/D pays this many days
  "sandwich_rule": true,             // leave-weekoff-leave ⇒ weekoff = leave
  "exit_trailing_absence_unpaid": true,
  "attendance_starts_on_join_date": true,

  "triggers": {
    "immediate_leave_after_joining_days": 7,
    "consecutive_leave_days": 2
  },

  "checks": [
    "N + approved_leave - E == L",
    "H == DM"
  ]
}
```

Checks are Python expressions evaluated per employee; available vars:
`A B C D E F G J H I N L M approved_leave leave_bucket DM LD`.

---

## Payroll formulas

- `H = A + B + C + D + E + F + G`
- `I = A + B + J + D + E + F` (after conversions from rules)
- `Approved week-off earned = (A + B) / days_per_week`
- Closing leave `L = N + approved_leave - E - F` (rollover) or `= approved_leave` (fixed)

---

## API quick reference

| Method | Path                              | Notes                               |
|--------|-----------------------------------|-------------------------------------|
| POST   | `/api/auth/register`              | `{company_name, username, password}`|
| POST   | `/api/auth/login`                 | `{username, password}`              |
| POST   | `/api/auth/logout`                |                                     |
| GET    | `/api/auth/me`                    |                                     |
| GET/POST/PUT/DELETE | `/api/locations[/:id]`  | scoped to your company              |
| GET/POST/PUT/DELETE | `/api/employees[/:id]`  |                                     |
| GET/POST/DELETE     | `/api/holidays[/:id]`   | `?location_id=…` to list            |
| POST   | `/api/attendance/upload`          | multipart CSV                       |
| GET    | `/api/attendance`                 | `?location_id&year&month` (grid)    |
| POST   | `/api/attendance/save`            | save grid                           |
| POST   | `/api/payroll/run`                | `{location_id, month, year}`        |
| GET    | `/api/payroll/report`             | `?run_id&format=csv|xlsx`           |

All endpoints require a session cookie from `/api/auth/login`.

---

## Tests

```bash
pytest
```

11 tests cover each spec rule (mid-week joiner week-off, sandwich, exit
trailing absence, female extra leave, triggers, holiday-multiplier, custom
checks, rollover vs fixed).

---

## Project layout

```
app/
  engine/calculator.py   pure-python rule engine
  main.py                FastAPI app (auth + CRUD + payroll)
  models.py              SQLAlchemy models
  schemas.py             Pydantic schemas
  auth.py                bcrypt / session helpers
  seed.py                sample data (ACME / admin / Jan 2025)
  static/                dashboard (index.html, login.html, style.css, app.js)
tests/test_engine.py     unit tests
sample_data/             example attendance CSV
run.sh                   one-command launcher
Dockerfile               containerized alternative
```

## Roadmap

- **Punch-app integration layer** (user asked to defer this)
- Admin role / multiple users per tenant
- Per-employee opening-leave roll-forward automation between payroll runs
- Editable attendance calendar directly on the dashboard (done — see Attendance tab)
