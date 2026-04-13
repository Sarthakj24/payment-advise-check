import csv
import io
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from . import models, schemas
from .engine import calculate_payroll, DEFAULT_RULE_CONFIG

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Attendance Payroll Calculator")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Bootstrap — seed sample data on first run
# ---------------------------------------------------------------------------
@app.on_event("startup")
def seed_sample_data():
    from .seed import seed
    seed()


# ---------------------------------------------------------------------------
# Root / dashboard
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/default-config")
def default_config():
    return DEFAULT_RULE_CONFIG


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
@app.post("/api/companies", response_model=schemas.CompanyOut)
def create_company(body: schemas.CompanyIn, db: Session = Depends(get_db)):
    c = models.Company(name=body.name)
    db.add(c); db.commit(); db.refresh(c)
    return c


@app.get("/api/companies", response_model=list[schemas.CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(models.Company).all()


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
@app.post("/api/locations", response_model=schemas.LocationOut)
def create_location(body: schemas.LocationIn, db: Session = Depends(get_db)):
    loc = models.Location(**body.model_dump())
    db.add(loc); db.commit(); db.refresh(loc)
    return loc


@app.put("/api/locations/{loc_id}", response_model=schemas.LocationOut)
def update_location(loc_id: int, body: schemas.LocationIn, db: Session = Depends(get_db)):
    loc = db.get(models.Location, loc_id)
    if not loc:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(loc, k, v)
    db.commit(); db.refresh(loc)
    return loc


@app.get("/api/locations", response_model=list[schemas.LocationOut])
def list_locations(company_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Location)
    if company_id:
        q = q.filter(models.Location.company_id == company_id)
    return q.all()


@app.get("/api/locations/{loc_id}", response_model=schemas.LocationOut)
def get_location(loc_id: int, db: Session = Depends(get_db)):
    loc = db.get(models.Location, loc_id)
    if not loc:
        raise HTTPException(404)
    return loc


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@app.post("/api/employees", response_model=schemas.EmployeeOut)
def create_employee(body: schemas.EmployeeIn, db: Session = Depends(get_db)):
    e = models.Employee(**body.model_dump())
    db.add(e); db.commit(); db.refresh(e)
    return e


@app.get("/api/employees", response_model=list[schemas.EmployeeOut])
def list_employees(location_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Employee)
    if location_id:
        q = q.filter(models.Employee.location_id == location_id)
    return q.all()


# ---------------------------------------------------------------------------
# Attendance CSV upload
# ---------------------------------------------------------------------------
@app.post("/api/attendance/upload")
async def upload_attendance(
    location_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    CSV columns: emp_code,day(YYYY-MM-DD),code(A..G),worked_on_holiday(0/1)
    """
    content = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    emps = {e.emp_code: e for e in db.query(models.Employee).filter_by(location_id=location_id).all()}
    n_added = 0
    for row in reader:
        emp = emps.get(row["emp_code"])
        if not emp:
            continue
        d = datetime.strptime(row["day"], "%Y-%m-%d").date()
        # delete duplicate for same (emp, day)
        db.query(models.AttendanceRecord).filter_by(employee_id=emp.id, day=d).delete()
        db.add(models.AttendanceRecord(
            employee_id=emp.id, day=d, code=row["code"].strip().upper(),
            worked_on_holiday=row.get("worked_on_holiday", "0") in ("1", "true", "True"),
        ))
        n_added += 1
    db.commit()
    return {"rows_ingested": n_added}


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------
@app.post("/api/payroll/run")
def run_payroll(body: schemas.PayrollRunIn, db: Session = Depends(get_db)):
    loc = db.get(models.Location, body.location_id)
    if not loc:
        raise HTTPException(404, "Location not found")

    run = models.PayrollRun(location_id=loc.id, month=body.month, year=body.year)
    db.add(run); db.commit(); db.refresh(run)

    employees = db.query(models.Employee).filter_by(location_id=loc.id).all()
    first = date(body.year, body.month, 1)
    if body.month == 12:
        last = date(body.year + 1, 1, 1)
    else:
        last = date(body.year, body.month + 1, 1)

    results = []
    for e in employees:
        recs = db.query(models.AttendanceRecord).filter(
            models.AttendanceRecord.employee_id == e.id,
            models.AttendanceRecord.day >= first,
            models.AttendanceRecord.day < last,
        ).all()
        rec_dicts = [{"day": r.day, "code": r.code, "worked_on_holiday": r.worked_on_holiday}
                     for r in recs]
        payload = calculate_payroll(
            employee={
                "emp_code": e.emp_code, "name": e.name, "gender": e.gender,
                "joining_date": e.joining_date, "exit_date": e.exit_date,
                "monthly_salary": e.monthly_salary, "opening_leave": e.opening_leave,
            },
            year=body.year, month=body.month, records=rec_dicts,
            rule_config=loc.rule_config,
        )
        db.add(models.PayrollResult(run_id=run.id, employee_id=e.id, payload=payload))
        results.append(payload)
    db.commit()
    return {"run_id": run.id, "results": results}


@app.get("/api/payroll/runs")
def list_runs(location_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.PayrollRun)
    if location_id:
        q = q.filter(models.PayrollRun.location_id == location_id)
    return [{"id": r.id, "location_id": r.location_id, "month": r.month,
             "year": r.year, "created_at": r.created_at.isoformat()} for r in q.all()]


@app.get("/api/payroll/runs/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db)):
    run = db.get(models.PayrollRun, run_id)
    if not run:
        raise HTTPException(404)
    return {
        "id": run.id, "month": run.month, "year": run.year,
        "results": [r.payload for r in run.results],
    }


@app.get("/api/payroll/report")
def payroll_report(run_id: int, format: str = "csv", db: Session = Depends(get_db)):
    run = db.get(models.PayrollRun, run_id)
    if not run:
        raise HTTPException(404)
    rows = [r.payload for r in run.results]

    if format == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "Payroll"
        headers = ["emp_code", "name", "gender", "H", "I", "A", "B", "C", "D", "E", "F", "G", "J",
                   "approved_leave", "leave_bucket", "L_closing",
                   "monthly_salary", "per_day", "gross_payable", "flags", "notes"]
        ws.append(headers)
        for r in rows:
            ws.append([
                r["employee"]["emp_code"], r["employee"]["name"], r["employee"]["gender"],
                r["H_total_days"], r["I_payable_days"],
                r["counts"]["A"], r["counts"]["B"], r["counts"]["C"], r["counts"]["D"],
                r["counts"]["E"], r["counts"]["F"], r["counts"]["G"], r["counts"]["J"],
                r["approved_leave"], r["leave_bucket"], r["leave_ledger"]["L_closing"],
                r["salary"]["monthly"], r["salary"]["per_day"], r["salary"]["gross_payable"],
                "; ".join(r["flags"]), "; ".join(r["notes"]),
            ])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename=payroll_{run_id}.xlsx'})

    # CSV default
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["emp_code", "name", "gender", "H", "I", "A", "B", "C", "D", "E", "F", "G", "J",
                "approved_leave", "leave_bucket", "L_closing",
                "monthly_salary", "per_day", "gross_payable", "flags", "notes"])
    for r in rows:
        w.writerow([
            r["employee"]["emp_code"], r["employee"]["name"], r["employee"]["gender"],
            r["H_total_days"], r["I_payable_days"],
            r["counts"]["A"], r["counts"]["B"], r["counts"]["C"], r["counts"]["D"],
            r["counts"]["E"], r["counts"]["F"], r["counts"]["G"], r["counts"]["J"],
            r["approved_leave"], r["leave_bucket"], r["leave_ledger"]["L_closing"],
            r["salary"]["monthly"], r["salary"]["per_day"], r["salary"]["gross_payable"],
            "; ".join(r["flags"]), "; ".join(r["notes"]),
        ])
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename=payroll_{run_id}.csv'})
