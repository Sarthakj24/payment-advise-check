const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
let lastRunId = null;

// Tabs
$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  $$(".panel").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("#" + t.dataset.tab).classList.add("active");
});

async function api(path, opts={}) {
  const r = await fetch(path, { headers: {"Content-Type": "application/json"}, ...opts });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function loadLocations() {
  const locs = await api("/api/locations");
  for (const sel of ["#run-location", "#cfg-location", "#emp-location", "#up-location"]) {
    $(sel).innerHTML = locs.map(l => `<option value="${l.id}">${l.name} (${l.code})</option>`).join("");
  }
}

async function loadDefault() {
  const d = await api("/api/default-config");
  $("#cfg-default").textContent = JSON.stringify(d, null, 2);
}

async function loadConfig() {
  const id = $("#cfg-location").value;
  if (!id) return;
  const loc = await api(`/api/locations/${id}`);
  $("#cfg-json").value = JSON.stringify(loc.rule_config, null, 2);
}

async function saveConfig() {
  const id = $("#cfg-location").value;
  const loc = await api(`/api/locations/${id}`);
  let cfg;
  try { cfg = JSON.parse($("#cfg-json").value); }
  catch(e) { alert("Invalid JSON: " + e.message); return; }
  loc.rule_config = cfg;
  await api(`/api/locations/${id}`, { method: "PUT", body: JSON.stringify(loc) });
  alert("Saved.");
}

async function loadEmployees() {
  const id = $("#emp-location").value;
  if (!id) return;
  const emps = await api(`/api/employees?location_id=${id}`);
  const rows = [
    "<tr><th>Code</th><th>Name</th><th>Gender</th><th>Joining</th><th>Exit</th><th>Salary</th><th>Opening leave</th></tr>",
    ...emps.map(e => `<tr>
      <td>${e.emp_code}</td><td>${e.name}</td><td>${e.gender}</td>
      <td>${e.joining_date}</td><td>${e.exit_date||""}</td>
      <td>${e.monthly_salary}</td><td>${e.opening_leave}</td>
    </tr>`)
  ];
  $("#emp-table").innerHTML = rows.join("");
}

async function runPayroll() {
  const body = {
    location_id: +$("#run-location").value,
    year: +$("#run-year").value,
    month: +$("#run-month").value,
  };
  const r = await api("/api/payroll/run", { method: "POST", body: JSON.stringify(body) });
  lastRunId = r.run_id;
  $("#dl-csv").disabled = false;
  $("#dl-xlsx").disabled = false;

  const header = "<tr><th>Emp</th><th>Name</th><th>H</th><th>I</th><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th><th>F</th><th>G</th><th>J</th><th>Approved</th><th>L close</th><th>Gross ₹</th><th>Flags / Notes / Checks</th></tr>";
  const rows = r.results.map(x => {
    const flags = x.flags.map(f => `<span class="flag">${f}</span>`).join("");
    const notes = x.notes.map(n => `<span class="note">${n}</span>`).join("");
    const chks = x.checks.map(c => `<span class="${c.pass?'check-ok':'check-fail'}">${c.pass?'✓':'✗'} ${c.expr}</span>`).join("<br>");
    return `<tr>
      <td>${x.employee.emp_code}</td><td>${x.employee.name}</td>
      <td>${x.H_total_days}</td><td>${x.I_payable_days}</td>
      <td>${x.counts.A}</td><td>${x.counts.B}</td><td>${x.counts.C}</td>
      <td>${x.counts.D}</td><td>${x.counts.E}</td><td>${x.counts.F}</td>
      <td>${x.counts.G}</td><td>${x.counts.J}</td>
      <td>${x.approved_leave}</td><td>${x.leave_ledger.L_closing}</td>
      <td>${x.salary.gross_payable}</td>
      <td>${flags}${notes}<br>${chks}</td>
    </tr>`;
  });
  $("#run-table").innerHTML = header + rows.join("");
  $("#run-summary").innerHTML = `<p>Run ID <b>${r.run_id}</b> · ${r.results.length} employees</p>`;
  $("#run-raw").textContent = JSON.stringify(r, null, 2);
}

async function uploadAttendance() {
  const loc = $("#up-location").value;
  const file = $("#up-file").files[0];
  if (!file) { alert("Pick a file"); return; }
  const fd = new FormData();
  fd.append("location_id", loc);
  fd.append("file", file);
  const r = await fetch("/api/attendance/upload", { method: "POST", body: fd });
  $("#up-result").textContent = await r.text();
}

$("#run-btn").onclick = runPayroll;
$("#cfg-reload").onclick = loadConfig;
$("#cfg-save").onclick = saveConfig;
$("#emp-reload").onclick = loadEmployees;
$("#up-btn").onclick = uploadAttendance;
$("#dl-csv").onclick = () => { if(lastRunId) location.href = `/api/payroll/report?run_id=${lastRunId}&format=csv`; };
$("#dl-xlsx").onclick = () => { if(lastRunId) location.href = `/api/payroll/report?run_id=${lastRunId}&format=xlsx`; };
$("#cfg-location").onchange = loadConfig;
$("#emp-location").onchange = loadEmployees;

(async () => {
  await loadLocations();
  await loadDefault();
  await loadConfig();
  await loadEmployees();
})();
