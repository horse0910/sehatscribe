"use strict";

const $ = (s) => document.querySelector(s);
const state = { enc: null, note: null, lang: "hi" };

const SAMPLE = `DOCTOR: Namaste, bataiye kya takleef hai?
DAUGHTER: Doctor sahab, papa ko teen din se bukhar hai, raat ko zyada hota hai.
PATIENT: Sar mein dard bhi hai aur badan dard ho raha hai.
DOCTOR: Ulti ya dast hua?
PATIENT: Nahi, ulti nahi hui.
DOCTOR: Koi dawai li hai?
DAUGHTER: Ghar pe crocin di thi.
DOCTOR: Chaliye BP aur temperature dekhte hain. BP 128/84, temperature 101.2, oxygen 97.
DOCTOR: Lagta hai viral fever hai, par malaria aur dengue ka shak hai. Malaria test aur CBC karwaiye.
DOCTOR: Paracetamol 650 mg din mein teen baar, teen din tak. Paani zyada pijiye, aaram kijiye.
DOCTOR: Do din baad report ke saath dobara aaiye.`;

// ---------------------------------------------------------------- helpers
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg, ms = 3200) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }, ...opts });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `HTTP ${res.status}`);
  }
  return data;
}
function busy(btn, on, label) {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.textContent; btn.textContent = label || "Working…"; btn.disabled = true; }
  else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
}
const show = (id) => $(id).classList.remove("hidden");

// ---------------------------------------------------------------- startup
async function init() {
  try {
    const h = await api("/api/health");
    const r = h.runtime;
    const npu = r.qnn_npu_available ? "<b>NPU ready</b>" : "NPU not detected";
    const llm = r.engines.llm_genie_npu ? "Llama 3.2 on NPU" : r.engines.llm_ort_genai ? "ONNX Runtime GenAI" : "rule engine";
    $("#runtime").innerHTML = `● Offline · ${npu} · drafting: ${esc(llm)} · v${esc(h.version)}`;
    if (!h.doctors_configured) $("#setup").showModal();
  } catch (e) {
    $("#runtime").textContent = "Server not reachable";
  }
}

$("#setup-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  try {
    await api("/api/doctors", { method: "POST", body: JSON.stringify(Object.fromEntries(f)) });
    $("#setup").close();
    $("#sign-form").doctor_id.value = f.get("doctor_id");
    toast("Doctor saved on this device");
  } catch (e) { toast(e.message); }
});

// ---------------------------------------------------------------- encounter
$("#new-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const body = {
    patient_name: f.patient_name.value || null,
    patient_age: f.patient_age.value ? Number(f.patient_age.value) : null,
    patient_sex: f.patient_sex.value || null,
    abha_number: f.abha_number.value || null,
    language: f.language.value,
    consent_given: f.consent_given.checked,
  };
  try {
    state.enc = await api("/api/encounters", { method: "POST", body: JSON.stringify(body) });
    $("#enc-id").textContent = `#${state.enc.id}`;
    show("#capture-card");
    ["#note-card", "#flags-card", "#sign-card", "#summary-card", "#draft-btn"].forEach((s) => $(s).classList.add("hidden"));
    $("#transcript-view").innerHTML = "";
    $("#signed").classList.add("hidden");
    $("#sign-form").classList.remove("hidden");
  } catch (e) { toast(e.message); }
});

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $("#tab-type").classList.toggle("hidden", t.dataset.tab !== "type");
  $("#tab-record").classList.toggle("hidden", t.dataset.tab !== "record");
}));

$("#load-sample").addEventListener("click", () => { $("#transcript-text").value = SAMPLE; });

$("#save-transcript").addEventListener("click", async (ev) => {
  const text = $("#transcript-text").value.trim();
  if (!text) return toast("Paste or type the consultation first");
  busy(ev.target, true);
  try {
    const tx = await api(`/api/encounters/${state.enc.id}/transcript`, { method: "POST", body: JSON.stringify({ text }) });
    renderTranscript(tx);
  } catch (e) { toast(e.message); } finally { busy(ev.target, false); }
});

function renderTranscript(tx) {
  $("#transcript-view").innerHTML = tx.utterances.map((u) => {
    const conf = u.confidence != null && u.confidence < 0.55 ? " lowconf" : "";
    return `<div class="utt ${esc(u.speaker)}"><span class="who">${esc(u.speaker.toUpperCase())}</span>` +
      `<span class="${conf}">${esc(u.text)}</span>${u.role_inferred ? ' <span class="inferred">(role inferred)</span>' : ""}</div>`;
  }).join("");
  show("#draft-btn");
}

// ---------------------------------------------------------------- audio
let recorder = null, chunks = [];
$("#rec-btn").addEventListener("click", async (ev) => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      ev.target.textContent = "● Start recording";
      await uploadAudio(new Blob(chunks, { type: recorder.mimeType }), "consult.webm");
    };
    recorder.start();
    ev.target.textContent = "■ Stop & transcribe";
    $("#rec-status").textContent = "Recording…";
  } catch (e) { toast("Microphone unavailable: " + e.message); }
});
$("#audio-file").addEventListener("change", (ev) => {
  const f = ev.target.files[0];
  if (f) uploadAudio(f, f.name);
  ev.target.value = "";
});
async function uploadAudio(blob, name) {
  const fd = new FormData(); fd.append("audio", blob, name);
  $("#rec-status").textContent = "Transcribing on this device…";
  try {
    const r = await api(`/api/encounters/${state.enc.id}/audio`, { method: "POST", body: fd });
    renderTranscript(r.transcript);
    const rtf = r.asr.rtf ? ` · RTF ${r.asr.rtf.toFixed(2)}` : "";
    $("#rec-status").textContent = `Transcribed with ${r.asr.engine}${rtf}. Audio discarded.`;
  } catch (e) { $("#rec-status").textContent = e.message; }
}

// ---------------------------------------------------------------- draft
$("#draft-btn").addEventListener("click", async (ev) => {
  busy(ev.target, true, "Drafting…");
  try {
    const r = await api(`/api/encounters/${state.enc.id}/draft`, { method: "POST" });
    state.note = r.note;
    const ms = Object.values(r.timings_ms).reduce((a, b) => a + b, 0);
    $("#engine").textContent = `${r.engine} · ${ms.toFixed(0)} ms`;
    renderNote(); renderFlags(r.flags);
    ["#note-card", "#flags-card", "#sign-card", "#summary-card"].forEach(show);
    loadSummary();
  } catch (e) { toast(e.message); } finally { busy(ev.target, false); }
});

const VITALS = [
  ["bp_systolic", "BP systolic", "mmHg"], ["bp_diastolic", "BP diastolic", "mmHg"], ["temperature_f", "Temp", "°F"],
  ["spo2", "SpO₂", "%"], ["pulse", "Pulse", "/min"], ["weight_kg", "Weight", "kg"], ["glucose_mg_dl", "Glucose", "mg/dL"],
];

function chipList(key, items, label) {
  return `<div class="chips">${items.map((x, i) => `<span class="chip">${esc(label(x))}<button title="Remove" data-del="${key}" data-i="${i}">×</button></span>`).join("") || '<span class="muted">None recorded</span>'}</div>`;
}

function renderNote() {
  const n = state.note;
  const sym = (s) => s.name + (s.duration_days ? ` · ${s.duration_days}d` : "") + (s.modifiers.length ? ` · ${s.modifiers.join(", ")}` : "") + (s.reported_by === "caregiver" ? " · per caregiver" : "");
  const dx = (d) => `${d.name} (${d.status})${d.icd10 ? " · " + d.icd10 : ""}`;
  $("#note").innerHTML = `
    <h3>Subjective</h3>${chipList("symptoms", n.symptoms, sym)}
    ${n.negatives.length ? `<p class="muted">Denies: ${esc(n.negatives.join(", "))}</p>` : ""}
    ${n.home_medications.length ? `<p class="muted">Already taken: ${esc(n.home_medications.map((h) => `${h.drug} (${h.mentioned_as})`).join(", "))}</p>` : ""}
    <h3>Objective · vitals <span class="pill">${esc(n.vitals.source)}</span></h3>
    <div class="vitals">${VITALS.map(([k, l, u]) => `<div class="vital"><small>${l} (${u})</small><input data-vital="${k}" type="number" step="any" value="${n.vitals[k] ?? ""}"></div>`).join("")}</div>
    <h3>Assessment</h3>${chipList("diagnoses", n.diagnoses, dx)}
    <h3>Plan · medications</h3>
    <table class="meds"><thead><tr><th>Drug</th><th>Dose</th><th>Unit</th><th>×/day</th><th>Days</th><th></th></tr></thead><tbody>
    ${n.medications.map((m, i) => `<tr>
      <td><input data-med="${i}" data-f="drug" value="${esc(m.drug)}"></td>
      <td><input data-med="${i}" data-f="dose" type="number" step="any" value="${m.dose ?? ""}"></td>
      <td><input data-med="${i}" data-f="unit" value="${esc(m.unit)}"></td>
      <td><input data-med="${i}" data-f="frequency_per_day" type="number" min="1" max="6" value="${m.frequency_per_day ?? ""}"></td>
      <td><input data-med="${i}" data-f="duration_days" type="number" min="1" value="${m.duration_days ?? ""}"></td>
      <td><button class="btn ghost" data-del="medications" data-i="${i}">×</button></td></tr>`).join("")}
    </tbody></table>
    <button class="btn ghost" id="add-med" type="button">+ Add medicine</button>
    <h3>Investigations</h3>${chipList("investigations", n.investigations, (x) => x)}
    <h3>Advice</h3>${chipList("advice", n.advice, (x) => x)}
    <h3>Follow-up</h3><label>Days<input id="follow" type="number" min="0" value="${n.follow_up_days ?? ""}"></label>`;
  $("#remarks").value = n.doctor_remarks || "";
}

$("#note").addEventListener("click", (ev) => {
  const del = ev.target.dataset.del;
  if (del) { state.note[del].splice(Number(ev.target.dataset.i), 1); renderNote(); }
  if (ev.target.id === "add-med") {
    collectEdits();
    state.note.medications.push({ drug: "", dose: null, unit: "mg", frequency_per_day: null, prn: false, duration_days: null, route: "oral" });
    renderNote();
  }
});

function num(v) { return v === "" || v == null ? null : Number(v); }
function collectEdits() {
  const n = state.note;
  document.querySelectorAll("[data-vital]").forEach((el) => {
    const k = el.dataset.vital, v = num(el.value);
    n.vitals[k] = v == null ? null : (["temperature_f", "weight_kg"].includes(k) ? v : Math.round(v));
  });
  document.querySelectorAll("[data-med]").forEach((el) => {
    const m = n.medications[Number(el.dataset.med)], f = el.dataset.f;
    m[f] = ["drug", "unit"].includes(f) ? el.value.trim() : num(el.value);
    if (["frequency_per_day", "duration_days"].includes(f) && m[f] != null) m[f] = Math.round(m[f]);
  });
  n.medications = n.medications.filter((m) => m.drug);
  n.follow_up_days = num($("#follow")?.value);
  n.doctor_remarks = $("#remarks").value;
}

$("#save-note").addEventListener("click", async (ev) => {
  collectEdits();
  busy(ev.target, true, "Saving…");
  try {
    const r = await api(`/api/encounters/${state.enc.id}/note`, { method: "PUT", body: JSON.stringify({ note: state.note }) });
    state.note = r.note; renderNote(); renderFlags(r.flags); loadSummary(); toast("Saved and re-checked");
  } catch (e) { toast(e.message); } finally { busy(ev.target, false); }
});

function renderFlags(flags) {
  $("#flags").innerHTML = flags.length
    ? flags.map((f) => `<div class="flag ${esc(f.severity)}"><b>${esc(f.severity.toUpperCase())} · ${esc(f.code)}</b>${esc(f.message)}</div>`).join("")
    : '<p class="ok">No issues found.</p>';
}

// ---------------------------------------------------------------- sign & outputs
$("#sign-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  collectEdits();
  const f = ev.target;
  try {
    await api(`/api/encounters/${state.enc.id}/note`, { method: "PUT", body: JSON.stringify({ note: state.note }) });
    const r = await api(`/api/encounters/${state.enc.id}/sign`, { method: "POST", body: JSON.stringify({ doctor_id: f.doctor_id.value, pin: f.pin.value }) });
    f.pin.value = "";
    f.classList.add("hidden");
    $("#signed-text").textContent = `Signed by ${r.signed_by} at ${new Date(r.signed_at).toLocaleString()}`;
    $("#fhir-link").href = `/api/encounters/${state.enc.id}/fhir`;
    show("#signed");
    document.querySelectorAll("#note input, #note button, #save-note, #remarks").forEach((el) => (el.disabled = true));
  } catch (e) { toast(e.message); }
});

document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  state.lang = b.dataset.lang;
  document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("active", x === b));
  loadSummary();
}));

async function loadSummary() {
  try {
    const s = await api(`/api/encounters/${state.enc.id}/summary?lang=${state.lang}`);
    $("#summary").innerHTML = s.lines.map((l) => `<div>${esc(l)}</div>`).join("");
  } catch (e) { $("#summary").textContent = e.message; }
}
$("#print-btn").addEventListener("click", () => window.print());

init();
