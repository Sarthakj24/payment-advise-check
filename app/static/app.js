const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);
let lastRunId = null;
let lastGrid = null;
let ME = null;

// ---------- Tabs ----------
$$(".tab").forEach(t => t.onclick = async () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  $$(".panel").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("#" + t.dataset.tab).classList.add("active");
  // On-demand data loads: re-populate locations first, then the tab's data
  try {
    if (t.dataset.tab === "tracker") {
      await loadLocations();
      await loadTracker();
    } else if (t.dataset.tab === "users" && ME && ME.is_admin) {
      await loadUsers();
    } else if (t.dataset.tab === "holidays") {
      await loadLocations(); loadHolidays();
    } else if (t.dataset.tab === "employees") {
      await loadLocations(); loadEmployees();
    }
  } catch (e) { /* ignore */ }
});

async function api(path, opts={}) {
  const isJSON = !(opts.body instanceof FormData);
  const r = await fetch(path, {
    headers: isJSON ? {"Content-Type": "application/json"} : undefined,
    ...opts,
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("unauth"); }
  if (!r.ok) throw new Error((await r.text()) || ("HTTP " + r.status));
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

// ---------- Whoami / logout ----------
async function whoami() {
  try {
    ME = await api("/api/auth/me");
    $("#who").textContent = `${ME.email} · ${ME.role.toUpperCase()} · company #${ME.company_id}`;
    applyRoleVisibility();
  } catch { location.href = "/login"; }
}
function applyRoleVisibility() {
  const isAdmin = !!(ME && ME.is_admin);
  // Hide admin-only tabs for KAMs
  $$("[data-admin-only]").forEach(el => { el.style.display = isAdmin ? "" : "none"; });
  // Hide Save buttons on Rule Config and Location form for non-admins
  const saveButtons = ["#cfg-save", "#cfg-save-json", "#loc-new"];
  saveButtons.forEach(s => { if ($(s)) $(s).style.display = isAdmin ? "" : "none"; });
  // If KAM landed on locations/users tab, bounce to Run Payroll
  if (!isAdmin) {
    const active = document.querySelector(".panel.active");
    if (active && (active.id === "locations" || active.id === "users")) {
      $$(".tab").forEach(x => x.classList.remove("active"));
      $$(".panel").forEach(x => x.classList.remove("active"));
      document.querySelector(".tab[data-tab=run]").classList.add("active");
      $("#run").classList.add("active");
    }
  }
}
$("#logout").onclick = async () => { await api("/api/auth/logout", {method: "POST"}); location.href = "/login"; };

// ---------- Location pickers ----------
async function loadLocations() {
  const locs = await api("/api/locations");
  const opts = locs.map(l => `<option value="${l.id}">${l.name} (${l.code})</option>`).join("");
  ["#run-location","#cfg-location","#emp-location","#up-location","#att-location","#hol-location","#trk-location"]
    .forEach(s => { if ($(s)) $(s).innerHTML = opts; });
  return locs;
}

let _defaultConfig = {};
async function loadDefault() {
  _defaultConfig = await api("/api/default-config");
  $("#cfg-default").textContent = JSON.stringify(_defaultConfig, null, 2);
}

function _mergeConfig(base, override) {
  const out = {...base};
  if (!override) return out;
  for (const [k, v] of Object.entries(override)) {
    if (v && typeof v === "object" && !Array.isArray(v) && typeof out[k] === "object" && !Array.isArray(out[k])) {
      out[k] = {...out[k], ...v};
    } else {
      out[k] = v;
    }
  }
  return out;
}

// ---------- Rule config form schema ----------
// Drives both the Rule Config tab and the Location form.
const RULE_SCHEMA = [
  { section: "Working Pattern" },
  { key: "week_pattern", label: "Week pattern",
    hint: "How many working days per week.",
    type: "select", options: [["5day","5 days (Sat+Sun off)"],["6day","6 days (Sun off)"],["alt_sat","6 days, alternate Sat off"],["roster","Roster (per-employee week-off)"]] },
  { key: "week_off_day", label: "Primary week-off day",
    hint: "Only used for 6-day pattern. 0=Mon … 6=Sun.",
    type: "select", options: [[0,"Monday"],[1,"Tuesday"],[2,"Wednesday"],[3,"Thursday"],[4,"Friday"],[5,"Saturday"],[6,"Sunday"]] },
  { key: "alt_sat_off_weeks", label: "Alt-Saturday off weeks",
    hint: "When pattern = alt_sat, which Saturdays (of the month) are off.",
    type: "csv_int", placeholder: "e.g. 2,4" },
  { key: "roster_mode", label: "Roster mode",
    hint: "If enabled, each employee has their own week-off day (set on the employee record). Overrides the week_off_day above.",
    type: "bool" },
  { key: "week_off_cap_percent", label: "Week-off cap %",
    hint: "PRECEDES everything. total_weekoffs / total_days must be ≤ this %. Excess week-offs convert to Absent. 0 disables.",
    type: "number", step: "0.1", min: 0 },

  { section: "Approved Leaves" },
  { key: "approved_leaves_per_month", label: "Approved leaves per month",
    hint: "Days of leave paid as approved. 0 means only week-offs are approved; all leaves count as absent.",
    type: "number", step: "0.5", min: 0 },
  { key: "leave_carry_forward", label: "Carry-forward policy",
    hint: "Fixed = leave bucket resets monthly. Rollover = unused leaves carry to next month.",
    type: "select", options: [["fixed","Fixed (reset monthly)"],["rollover","Rollover (carry forward)"]] },
  { key: "female_extra_leave", label: "Female extra leave",
    hint: "Additional non-carry-forward leave for female employees. 0 to disable.",
    type: "number", step: "0.5", min: 0 },
  { key: "excess_leave_to_absent", label: "Excess leave → Absent",
    hint: "Leaves beyond the approved bucket convert to Absent (G).",
    type: "bool" },

  { section: "Holiday & Week-off Rules" },
  { key: "holiday_work_multiplier", label: "Holiday-work multiplier",
    hint: "If an employee works on a week-off (C) or holiday (D), pay this many days. 1.0 = single; 2.0 = double.",
    type: "number", step: "0.1", min: 0 },
  { key: "sandwich_rule", label: "Sandwich rule",
    hint: "If pre & post days of a week-off/holiday are both leaves, count the week-off as leave too.",
    type: "bool" },

  { section: "Joining / Exit" },
  { key: "attendance_starts_on_join_date", label: "Attendance starts on joining",
    hint: "Days before joining date are ignored, not counted as absent.",
    type: "bool" },
  { key: "exit_trailing_absence_unpaid", label: "Exit trailing absence unpaid",
    hint: "If employee leaves X but is absent on X-1, X-2, … then exit effectively moves to last attended day.",
    type: "bool" },

  { section: "Triggers / Flags" },
  { key: "triggers.immediate_leave_after_joining_days", label: "Flag: immediate leave after joining (within N days)",
    hint: "Flag employees who take a leave within N days of their joining date. 0 disables.",
    type: "number", step: 1, min: 0 },
  { key: "triggers.consecutive_leave_days", label: "Flag: consecutive leave days ≥ N",
    hint: "Flag employees with a streak of N or more leave days. 0 disables.",
    type: "number", step: 1, min: 0 },

  { section: "Vendor Upload Code Mapping" },
  { key: "vendor_code_map.P",  label: "Vendor 'P' → internal code",  hint: "Enter A (Present). Must be one of A/B/C/D/E/F/G.",           type: "text" },
  { key: "vendor_code_map.HD", label: "Vendor 'HD' → internal code", hint: "Enter B (Half-day Present). Must be one of A/B/C/D/E/F/G.",  type: "text" },
  { key: "vendor_code_map.WO", label: "Vendor 'WO' → internal code", hint: "Enter C (Week Off). Must be one of A/B/C/D/E/F/G.",          type: "text" },
  { key: "vendor_code_map.H",  label: "Vendor 'H' → internal code",  hint: "Enter D (Holiday). Must be one of A/B/C/D/E/F/G.",           type: "text" },
  { key: "vendor_code_map.L",  label: "Vendor 'L' → internal code",  hint: "Enter E (Leave Full Day). Must be one of A/B/C/D/E/F/G.",    type: "text" },
  { key: "vendor_code_map.HL", label: "Vendor 'HL' → internal code", hint: "Enter F (Half Leave). Must be one of A/B/C/D/E/F/G.",        type: "text" },
  { key: "vendor_code_map.A",  label: "Vendor 'A' → internal code",  hint: "Enter G (Absent). Must be one of A/B/C/D/E/F/G.",            type: "text" },

  { section: "Custom Checks" },
  { key: "checks", label: "Validation formulas",
    hint: "One expression per line. Variables: A,B,C,D,E,F,G,J,H,I,N,L,M,approved_leave,leave_bucket,DM,LD. Example: H == DM",
    type: "lines" },
];

function _get(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function _set(obj, path, val) {
  const parts = path.split(".");
  const last = parts.pop();
  const target = parts.reduce((o, k) => (o[k] ??= {}), obj);
  target[last] = val;
}

function renderRuleForm(container, cfg) {
  container.innerHTML = "";
  for (const item of RULE_SCHEMA) {
    if (item.section) {
      const h = document.createElement("div");
      h.className = "cfg-hdr"; h.textContent = item.section;
      container.appendChild(h);
      continue;
    }
    const row = document.createElement("div"); row.className = "cfg-row";
    const l = document.createElement("div"); l.className = "cfg-label";
    l.innerHTML = `<b>${item.label}</b>${item.hint ? `<small>${item.hint}</small>` : ""}`;
    const v = document.createElement("div"); v.className = "cfg-value";

    const cur = _get(cfg, item.key);
    let input;
    if (item.type === "select") {
      input = document.createElement("select");
      for (const [val, lab] of item.options) {
        const o = document.createElement("option");
        o.value = val; o.textContent = lab;
        if (String(cur) === String(val)) o.selected = true;
        input.appendChild(o);
      }
    } else if (item.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox"; input.checked = !!cur;
    } else if (item.type === "number") {
      input = document.createElement("input");
      input.type = "number";
      if (item.step != null) input.step = item.step;
      if (item.min != null) input.min = item.min;
      input.value = cur ?? 0;
    } else if (item.type === "csv_int") {
      input = document.createElement("input");
      input.type = "text"; input.placeholder = item.placeholder || "";
      input.value = Array.isArray(cur) ? cur.join(",") : (cur || "");
    } else if (item.type === "lines") {
      input = document.createElement("textarea");
      input.value = Array.isArray(cur) ? cur.join("\n") : (cur || "");
    } else {
      input = document.createElement("input");
      input.type = "text"; input.value = cur ?? "";
    }
    input.dataset.key = item.key; input.dataset.type = item.type;
    v.appendChild(input);
    row.appendChild(l); row.appendChild(v);
    container.appendChild(row);
  }
}

function readRuleForm(container) {
  const cfg = {};
  container.querySelectorAll("[data-key]").forEach(el => {
    const k = el.dataset.key, t = el.dataset.type;
    let val;
    if (t === "bool") val = el.checked;
    else if (t === "number") val = parseFloat(el.value);
    else if (t === "select") {
      val = el.value;
      // coerce numeric selects (week_off_day)
      if (!isNaN(+val) && val !== "") val = +val;
    } else if (t === "csv_int") {
      val = el.value.split(",").map(s => s.trim()).filter(Boolean).map(Number).filter(n => !isNaN(n));
    } else if (t === "lines") {
      val = el.value.split("\n").map(s => s.trim()).filter(Boolean);
    } else {
      val = el.value;
    }
    _set(cfg, k, val);
  });
  return cfg;
}

// ---------- Rule config tab ----------
async function loadConfig() {
  const id = $("#cfg-location").value; if (!id) return;
  const loc = await api(`/api/locations/${id}`);
  const merged = _mergeConfig(_defaultConfig, loc.rule_config);
  renderRuleForm($("#cfg-form"), merged);
  $("#cfg-json").value = JSON.stringify(loc.rule_config, null, 2);
}
async function saveConfig() {
  const id = $("#cfg-location").value;
  const loc = await api(`/api/locations/${id}`);
  loc.rule_config = readRuleForm($("#cfg-form"));
  await api(`/api/locations/${id}`, { method: "PUT", body: JSON.stringify(loc) });
  $("#cfg-json").value = JSON.stringify(loc.rule_config, null, 2);
  alert("Saved.");
}
async function saveConfigJSON() {
  const id = $("#cfg-location").value;
  const loc = await api(`/api/locations/${id}`);
  let cfg; try { cfg = JSON.parse($("#cfg-json").value); }
  catch(e) { alert("Invalid JSON: " + e.message); return; }
  loc.rule_config = cfg;
  await api(`/api/locations/${id}`, { method: "PUT", body: JSON.stringify(loc) });
  renderRuleForm($("#cfg-form"), cfg);
  alert("Saved.");
}

// ---------- Employees tab ----------
async function loadEmployees() {
  const id = $("#emp-location").value; if (!id) return;
  const emps = await api(`/api/employees?location_id=${id}`);
  const DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const rows = [
    "<tr><th>Code</th><th>Title</th><th>Name</th><th>Gender</th><th>Joining</th><th>Exit</th><th>Salary</th><th>Opening leave</th><th>Week off</th><th></th></tr>",
    ...emps.map(e => `<tr>
      <td>${e.emp_code}</td><td>${e.title||""}</td><td>${e.name}</td><td>${e.gender}</td>
      <td>${e.joining_date}</td><td>${e.exit_date||""}</td>
      <td>${e.monthly_salary}</td><td>${e.opening_leave}</td>
      <td>${e.week_off_day != null ? DAY_NAMES[e.week_off_day] : ""}</td>
      <td>
        <button class="secondary" onclick='editEmp(${JSON.stringify(e)})'>Edit</button>
        <button class="danger" onclick='delEmp(${e.id})'>Delete</button>
      </td>
    </tr>`)
  ];
  $("#emp-table").innerHTML = rows.join("");
}
function empForm(e) {
  const form = $("#emp-form");
  form.style.display = "";
  $("#emp-form-title").textContent = e.id ? "Edit employee" : "New employee";
  for (const k of ["id","emp_code","title","name","gender","joining_date","exit_date","monthly_salary","opening_leave"]) {
    const el = form.querySelector(`[name=${k}]`);
    if (el) el.value = e[k] ?? "";
  }
  const wo = form.querySelector("[name=week_off_day]");
  if (wo) wo.value = (e.week_off_day == null ? "" : String(e.week_off_day));
}
window.editEmp = e => empForm(e);
window.delEmp = async id => {
  if (!confirm("Delete employee?")) return;
  await api(`/api/employees/${id}`, { method: "DELETE" });
  loadEmployees();
};
$("#emp-new").onclick = () => empForm({});
$("#emp-cancel").onclick = () => $("#emp-form").style.display = "none";
$("#emp-save").onclick = async () => {
  const f = $("#emp-form");
  const woRaw = f.querySelector("[name=week_off_day]").value;
  const body = {
    location_id: +$("#emp-location").value,
    emp_code: f.querySelector("[name=emp_code]").value,
    title: f.querySelector("[name=title]").value || null,
    name: f.querySelector("[name=name]").value,
    gender: f.querySelector("[name=gender]").value,
    joining_date: f.querySelector("[name=joining_date]").value,
    exit_date: f.querySelector("[name=exit_date]").value || null,
    monthly_salary: +f.querySelector("[name=monthly_salary]").value || 0,
    opening_leave: +f.querySelector("[name=opening_leave]").value || 0,
    week_off_day: woRaw === "" ? null : +woRaw,
  };
  const id = f.querySelector("[name=id]").value;
  if (id) await api(`/api/employees/${id}`, { method: "PUT", body: JSON.stringify(body) });
  else await api(`/api/employees`, { method: "POST", body: JSON.stringify(body) });
  $("#emp-form").style.display = "none";
  loadEmployees();
};

// ---------- Locations tab ----------
async function loadLocationsTable() {
  const locs = await api("/api/locations");
  const rows = [
    "<tr><th>Code</th><th>Name</th><th>Rule summary</th><th></th></tr>",
    ...locs.map(l => `<tr>
      <td>${l.code}</td><td>${l.name}</td>
      <td><code>${JSON.stringify(l.rule_config).slice(0,80)}…</code></td>
      <td>
        <button class="secondary" onclick='editLoc(${JSON.stringify(l)})'>Edit</button>
        <button class="danger" onclick='delLoc(${l.id})'>Delete</button>
      </td>
    </tr>`)
  ];
  $("#loc-table").innerHTML = rows.join("");
}
function locForm(l) {
  const f = $("#loc-form"); f.style.display = "";
  $("#loc-form-title").textContent = l.id ? "Edit location" : "New location";
  f.querySelector("[name=id]").value = l.id || "";
  f.querySelector("[name=code]").value = l.code || "";
  f.querySelector("[name=name]").value = l.name || "";
  renderRuleForm($("#loc-cfg-form"), _mergeConfig(_defaultConfig, l.rule_config));
}
window.editLoc = l => locForm(l);
window.delLoc = async id => {
  if (!confirm("Delete location (and its employees)?")) return;
  await api(`/api/locations/${id}`, { method: "DELETE" });
  refreshAll();
};
$("#loc-new").onclick = () => locForm({});
$("#loc-cancel").onclick = () => $("#loc-form").style.display = "none";
$("#loc-save").onclick = async () => {
  const f = $("#loc-form");
  const body = {
    company_id: 0, // server sets from session
    code: f.querySelector("[name=code]").value,
    name: f.querySelector("[name=name]").value,
    rule_config: readRuleForm($("#loc-cfg-form")),
  };
  const id = f.querySelector("[name=id]").value;
  if (id) await api(`/api/locations/${id}`, { method: "PUT", body: JSON.stringify(body) });
  else await api(`/api/locations`, { method: "POST", body: JSON.stringify(body) });
  $("#loc-form").style.display = "none";
  refreshAll();
};

// ---------- Holidays tab ----------
async function loadHolidays() {
  const id = $("#hol-location").value; if (!id) return;
  const list = await api(`/api/holidays?location_id=${id}`);
  $("#hol-table").innerHTML = [
    "<tr><th>Date</th><th>Name</th><th></th></tr>",
    ...list.map(h => `<tr><td>${h.day}</td><td>${h.name}</td>
      <td><button class="danger" onclick='delHol(${h.id})'>Delete</button></td></tr>`)
  ].join("");
}
window.delHol = async id => {
  await api(`/api/holidays/${id}`, { method: "DELETE" });
  loadHolidays();
};
$("#hol-add").onclick = async () => {
  const body = {
    location_id: +$("#hol-location").value,
    day: $("#hol-day").value,
    name: $("#hol-name").value || "Holiday",
  };
  if (!body.day) return alert("Pick a date");
  await api(`/api/holidays`, { method: "POST", body: JSON.stringify(body) });
  $("#hol-day").value = ""; $("#hol-name").value = "";
  loadHolidays();
};

// ---------- Attendance grid ----------
const CODES = ["", "A", "B", "C", "D", "E", "F", "G"];
const CODE_NAMES = {"":"—","A":"Present","B":"Half Day","C":"Week Off","D":"Holiday","E":"Leave","F":"Half Leave","G":"Absent"};
const DAYNAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

function _attCellClass(code) {
  return code ? `att-code-${code}` : "att-code-empty";
}

async function loadAttendance() {
  const body = { location_id: +$("#att-location").value,
                 year: +$("#att-year").value, month: +$("#att-month").value };
  const data = await api(`/api/attendance?location_id=${body.location_id}&year=${body.year}&month=${body.month}`);
  lastGrid = data;
  const mm = String(body.month).padStart(2, "0");

  // Build day header: number + day-of-week abbreviation
  const dayHdr = Array.from({length: data.dm}, (_, i) => {
    const dd = String(i + 1).padStart(2, "0");
    const dt = new Date(body.year, body.month - 1, i + 1);
    const wd = dt.getDay(); // 0=Sun
    const holName = data.holidays[`${body.year}-${mm}-${dd}`] || "";
    const cls = holName ? "att-hol" : wd === 0 ? "att-sun" : "";
    return `<th class="${cls}" title="${holName}">${i+1}<br><small>${DAYNAMES[(wd+6)%7]}</small></th>`;
  }).join("");

  const rows = data.rows.map((row, ri) => {
    const cells = row.days.map((d, di) => {
      const opts = CODES.map(c =>
        `<option value="${c}"${c===d.code?" selected":""}>${c||"—"}</option>`
      ).join("");
      const chk = (d.code==="C"||d.code==="D")
        ? `<input type=checkbox class="att-hol-chk" data-r=${ri} data-d=${di} ${d.worked_on_holiday?"checked":""} title="Worked?">`
        : "";
      return `<td class="att-cell ${_attCellClass(d.code)}"><select data-r=${ri} data-d=${di}>${opts}</select>${chk}</td>`;
    }).join("");
    return `<tr><td><b>${row.emp_code}</b><br><small>${row.name}</small></td>${cells}</tr>`;
  }).join("");

  $("#att-table").innerHTML = `<thead><tr><th>Employee</th>${dayHdr}</tr></thead><tbody>${rows}</tbody>`;

  // Wire up change handlers — update data + color
  $$("#att-table select").forEach(s => {
    s.onchange = e => {
      const r = +e.target.dataset.r, d = +e.target.dataset.d;
      const code = e.target.value;
      lastGrid.rows[r].days[d].code = code;
      loadAttendance._dirty = true;
      const td = e.target.closest("td");
      td.className = `att-cell ${_attCellClass(code)}`;
    };
  });
  $$("#att-table .att-hol-chk").forEach(c => c.onchange = e => {
    const r = +e.target.dataset.r, d = +e.target.dataset.d;
    lastGrid.rows[r].days[d].worked_on_holiday = e.target.checked;
    loadAttendance._dirty = true;
  });
}
$("#att-load").onclick = loadAttendance;
$("#att-save").onclick = async () => {
  if (!lastGrid) return;
  await api("/api/attendance/save", { method: "POST",
    body: JSON.stringify({ location_id: +$("#att-location").value, rows: lastGrid.rows }) });
  alert("Saved.");
};

// ---------- Attendance tracker (P/A/W/H/L) ----------
async function loadTracker() {
  const loc = $("#trk-location").value;
  const y = +$("#trk-year").value, m = +$("#trk-month").value;
  if (!loc) return;
  const data = await api(`/api/attendance/tracker?location_id=${loc}&year=${y}&month=${m}`);
  const mm = String(m).padStart(2, "0");
  const daysHdr = Array.from({length: data.dm}, (_, i) => {
    const dd = String(i + 1).padStart(2, "0");
    const dt = new Date(y, m - 1, i + 1);
    const wd = dt.getDay();
    const holName = data.holidays[`${y}-${mm}-${dd}`] || "";
    const cls = holName ? "holiday" : wd === 0 ? "att-sun" : "";
    return `<th class="${cls}" title="${holName}">${i+1}<br><small>${DAYNAMES[(wd+6)%7]}</small></th>`;
  }).join("");
  const sumHdr = `<th class="trk-sum">Present</th><th class="trk-sum">Absent</th><th class="trk-sum">Week Off</th><th class="trk-sum">Holiday</th><th class="trk-sum">Leave</th>`;
  const rows = data.rows.map(r => {
    const cells = r.days.map(c => {
      const cls = c === "P" ? "trk-p" : c === "A" ? "trk-a" :
                  c === "W" ? "trk-w" : c === "H" ? "trk-h" :
                  c === "L" ? "trk-l" : "trk-o";
      return `<td class="trk-cell ${cls}">${c}</td>`;
    }).join("");
    const s = r.summary;
    return `<tr>
      <td><b>${r.emp_code}</b><br><small>${r.title ? r.title + ' ' : ''}${r.name}</small></td>
      ${cells}
      <td class="trk-sum-cell">${s.P}</td><td class="trk-sum-cell">${s.A}</td>
      <td class="trk-sum-cell">${s.W}</td><td class="trk-sum-cell">${s.H}</td>
      <td class="trk-sum-cell">${s.L}</td>
    </tr>`;
  }).join("");
  $("#trk-table").innerHTML =
    `<thead><tr><th>Employee</th>${daysHdr}${sumHdr}</tr></thead><tbody>${rows}</tbody>`;
}
$("#trk-load").onclick = loadTracker;

// ---------- Users (admin only) ----------
let _allLocations = [];
async function loadUsers() {
  try {
    const list = await api("/api/users");
    _allLocations = await api("/api/locations");
    const locMap = Object.fromEntries(_allLocations.map(l => [l.id, `${l.name} (${l.code})`]));

    const userLocs = {};
    for (const u of list) {
      try {
        const data = await api(`/api/users/${u.id}/locations`);
        userLocs[u.id] = data.location_ids || [];
      } catch { userLocs[u.id] = []; }
    }

    $("#usr-table").innerHTML = [
      "<tr><th>Email</th><th>Role</th><th>Assigned Locations</th><th></th></tr>",
      ...list.map(u => {
        const isAdmin = (u.role || "").toLowerCase() === "admin";
        const locNames = isAdmin
          ? "<em>All (admin)</em>"
          : (userLocs[u.id] || []).map(id => locMap[id] || `#${id}`).join(", ") || "<em>None</em>";
        return `<tr>
          <td>${u.email}</td><td>${u.role}</td>
          <td>${locNames}</td>
          <td>
            ${isAdmin ? "" : `<button class="secondary" onclick='manageUserLocs(${u.id}, "${u.email}")'>Locations</button>`}
            <button class="danger" onclick='delUser(${u.id})'>Delete</button>
          </td>
        </tr>`;
      })
    ].join("");
  } catch (e) { /* non-admin — ignore */ }
}

let _editingUserLocUid = null;
window.manageUserLocs = async (uid, email) => {
  _editingUserLocUid = uid;
  $("#usr-loc-title").textContent = `Assign Locations — ${email}`;
  const data = await api(`/api/users/${uid}/locations`);
  const assigned = new Set(data.location_ids || []);
  const locs = _allLocations.length ? _allLocations : await api("/api/locations");
  $("#usr-loc-checks").innerHTML = locs.map(l =>
    `<label style="display:block;margin:4px 0">
      <input type="checkbox" value="${l.id}" ${assigned.has(l.id) ? "checked" : ""}>
      ${l.name} (${l.code})
    </label>`
  ).join("");
  $("#usr-loc-modal").style.display = "";
};
$("#usr-loc-cancel").onclick = () => { $("#usr-loc-modal").style.display = "none"; };
$("#usr-loc-save").onclick = async () => {
  const ids = [...$$("#usr-loc-checks input:checked")].map(el => +el.value);
  await api(`/api/users/${_editingUserLocUid}/locations`, {
    method: "PUT", body: JSON.stringify({ location_ids: ids })
  });
  $("#usr-loc-modal").style.display = "none";
  loadUsers();
};

window.delUser = async id => {
  if (!confirm("Delete user?")) return;
  await api(`/api/users/${id}`, { method: "DELETE" });
  loadUsers();
};
if ($("#usr-add")) $("#usr-add").onclick = async () => {
  const body = {
    email: $("#usr-name").value.trim(),
    password: $("#usr-pw").value,
    role: $("#usr-role").value,
  };
  if (!body.email || !body.password) return alert("Email and password required");
  await api("/api/users", { method: "POST", body: JSON.stringify(body) });
  $("#usr-name").value = ""; $("#usr-pw").value = "";
  loadUsers();
};

// ---------- Run payroll ----------
async function runPayroll() {
  const body = { location_id: +$("#run-location").value, year: +$("#run-year").value, month: +$("#run-month").value };
  const r = await api("/api/payroll/run", { method: "POST", body: JSON.stringify(body) });
  lastRunId = r.run_id;
  $("#dl-csv").disabled = false; $("#dl-xlsx").disabled = false; $("#dl-checked").disabled = false;

  const header = `<tr>
    <th>Emp Code</th><th>Title</th><th>Name</th>
    <th>Total Days</th><th>Payable Days</th>
    <th>Present</th><th>Half Present</th><th>Week Off</th><th>Holiday</th>
    <th>Leave</th><th>Half Leave</th><th>Absent</th><th>Holiday Work</th>
    <th>Approved Leave</th><th>Closing Leave</th>
    <th>Gross ₹</th><th>Flags / Notes / Checks</th>
  </tr>`;
  const rows = r.results.map(x => {
    const flags = x.flags.map(f => `<span class="flag">${f}</span>`).join("");
    const notes = x.notes.map(n => `<span class="note">${n}</span>`).join("");
    const chks = x.checks.map(c => `<span class="${c.pass?'check-ok':'check-fail'}">${c.pass?'✓':'✗'} ${c.expr}</span>`).join("<br>");
    return `<tr>
      <td>${x.employee.emp_code}</td><td>${x.employee.title||""}</td><td>${x.employee.name}</td>
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

// ---------- Vendor upload (wide format) ----------
let _lastUploadParams = null;
async function uploadAttendance() {
  const file = $("#up-file").files[0];
  if (!file) { alert("Pick a file"); return; }
  const fd = new FormData();
  fd.append("location_id", $("#up-location").value);
  fd.append("file", file);
  try {
    const r = await fetch("/api/attendance/upload-wide", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) { $("#up-result").textContent = "Error: " + (data.detail || JSON.stringify(data)); return; }
    let msg = `Rows processed: ${data.rows_processed}\nEmployees created: ${data.employees_created}\nAttendance saved: ${data.attendance_saved}`;
    if (data.skipped && data.skipped.length) msg += "\n\nSkipped:\n" + data.skipped.join("\n");
    $("#up-result").textContent = msg;
    _lastUploadParams = { location_id: $("#up-location").value, year: $("#up-year").value, month: $("#up-month").value };
    $("#up-analysis").disabled = false;
    $("#up-analysis-hint").style.display = "";
    refreshAll();
  } catch (e) { $("#up-result").textContent = "Error: " + e.message; }
}

// ---------- Wire up ----------
$("#run-btn").onclick = runPayroll;
$("#cfg-reload").onclick = loadConfig;
$("#cfg-save").onclick = saveConfig;
$("#cfg-save-json").onclick = saveConfigJSON;
$("#emp-reload").onclick = loadEmployees;
$("#loc-reload").onclick = loadLocationsTable;
$("#up-btn").onclick = uploadAttendance;
$("#up-tmpl-csv").onclick = () => {
  const loc = $("#up-location").value, y = $("#up-year").value, m = $("#up-month").value;
  if (!loc) return alert("Pick a location");
  location.href = `/api/attendance/upload-template?location_id=${loc}&year=${y}&month=${m}&fmt=csv`;
};
$("#up-tmpl-xlsx").onclick = () => {
  const loc = $("#up-location").value, y = $("#up-year").value, m = $("#up-month").value;
  if (!loc) return alert("Pick a location");
  location.href = `/api/attendance/upload-template?location_id=${loc}&year=${y}&month=${m}&fmt=xlsx`;
};
$("#dl-csv").onclick = () => { if(lastRunId) location.href = `/api/payroll/report?run_id=${lastRunId}&format=csv`; };
$("#dl-xlsx").onclick = () => { if(lastRunId) location.href = `/api/payroll/report?run_id=${lastRunId}&format=xlsx`; };
$("#dl-checked").onclick = () => { if(lastRunId) location.href = `/api/payroll/checked-report?run_id=${lastRunId}`; };
$("#up-analysis").onclick = () => {
  const p = _lastUploadParams;
  if (!p) return alert("Upload attendance first");
  location.href = `/api/attendance/upload-analysis?location_id=${p.location_id}&year=${p.year}&month=${p.month}`;
};
$("#cfg-location").onchange = loadConfig;
$("#emp-location").onchange = loadEmployees;
$("#hol-location").onchange = loadHolidays;

async function refreshAll() {
  await loadLocations();
  if (ME && ME.is_admin) {
    await loadLocationsTable();
    await loadUsers();
  }
  await loadEmployees();
  await loadHolidays();
  await loadConfig();
}

(async () => {
  await whoami();
  await loadDefault();
  await refreshAll();
})();
