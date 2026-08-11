"use strict";

const $ = (id) => document.getElementById(id);
const state = { kb: null, evolution: null };

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, body) {
  const options = { method: "GET", headers: { "Accept": "application/json" } };
  if (body) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  return response.json();
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
  });
});

/* ---------- knowledge base ---------- */
async function loadKb() {
  state.kb = await api("/api/kb/overview");
  const deptSelect = $("deptSelect");
  deptSelect.innerHTML = "";
  state.kb.departments.forEach((department) => {
    const option = document.createElement("option");
    option.value = department.name;
    option.textContent = `${department.name}（${department.disease_count}）`;
    deptSelect.appendChild(option);
  });
  renderKb();
}

function renderKb() {
  const wrap = $("kbOverview");
  wrap.innerHTML = "";
  state.kb.departments.forEach((department) => {
    const card = document.createElement("div");
    card.className = "kb-card";
    card.innerHTML = `
      <h3>${department.name}</h3>
      <div class="count">${department.disease_count} 种疾病</div>
      <div class="disease-list">
        ${department.diseases.map((d) => `<span class="tag" title="${d.id}">${d.name}</span>`).join("")}
      </div>`;
    wrap.appendChild(card);
  });
}

$("deptSelect").addEventListener("change", () => {
  const department = state.kb.departments.find((d) => d.name === $("deptSelect").value);
  const diseaseSelect = $("diseaseSelect");
  diseaseSelect.innerHTML = '<option value="">随机疾病</option>';
  department.diseases.forEach((disease) => {
    const option = document.createElement("option");
    option.value = disease.id;
    option.textContent = disease.name;
    diseaseSelect.appendChild(option);
  });
});

$("randomBtn").addEventListener("click", () => {
  $("diseaseSelect").value = "";
});

$("modelSelect").addEventListener("change", () => {
  $("statusText").textContent = $("modelSelect").value === "llm" ? "DeepSeek 推理" : "离线规则模式";
});

/* ---------- pixel hospital scene ---------- */
const canvas = $("hospitalCanvas");
const ctx = canvas.getContext("2d");

const stations = {
  disease_onset: { x: 58, y: 290 },
  triage: { x: 168, y: 150 },
  registration: { x: 168, y: 396 },
  symptom_question: { x: 300, y: 270 },
  symptom_answer: { x: 300, y: 270 },
  consultation: { x: 460, y: 270 },
  examination: { x: 668, y: 150 },
  diagnosis: { x: 460, y: 270 },
  consultation_round: { x: 460, y: 270 },
  consultation_summary: { x: 460, y: 270 },
  treatment: { x: 668, y: 396 },
  follow_up: { x: 902, y: 270 },
  end: { x: 902, y: 270 },
};

const rooms = [
  { name: "入口", x: 30, y: 250, w: 70, h: 80 },
  { name: "分诊台", x: 128, y: 110, w: 90, h: 80 },
  { name: "挂号处", x: 128, y: 356, w: 90, h: 80 },
  { name: "候诊区", x: 258, y: 230, w: 110, h: 80 },
  { name: "诊室", x: 400, y: 230, w: 120, h: 80 },
  { name: "检查室", x: 566, y: 110, w: 90, h: 80 },
  { name: "药房", x: 566, y: 356, w: 90, h: 80 },
  { name: "出口", x: 872, y: 250, w: 70, h: 80 },
];

function drawHospital() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#dfe4ea";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(255,255,255,0.55)";
  ctx.lineWidth = 1;
  for (let x = 0; x < canvas.width; x += 24) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
  }
  for (let y = 0; y < canvas.height; y += 24) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  rooms.forEach((room) => {
    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(room.x, room.y, room.w, room.h);
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 3;
    ctx.strokeRect(room.x, room.y, room.w, room.h);
    ctx.fillStyle = "#475569";
    ctx.font = "13px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(room.name, room.x + room.w / 2, room.y + room.h / 2 + 5);
    ctx.fillStyle = "#cbd5e1";
    ctx.fillRect(room.x + room.w / 2 - 8, room.y + room.h - 6, 16, 6);
  });

  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px 'Microsoft YaHei', sans-serif";
  ctx.fillText("MedAgent-Hospital · 仿真医院", 478, 24);
}

function drawPerson(x, y, opts) {
  const px = Math.round(x);
  const py = Math.round(y);
  ctx.fillStyle = "rgba(15, 23, 42, 0.18)";
  ctx.fillRect(px - 8, py - 3, 16, 5);
  ctx.fillStyle = "#2f3542";
  ctx.fillRect(px - 6, py - 12, 5, 12);
  ctx.fillRect(px + 1, py - 12, 5, 12);
  ctx.fillStyle = opts.body;
  ctx.fillRect(px - 8, py - 24, 16, 13);
  ctx.fillStyle = opts.trim || opts.body;
  ctx.fillRect(px - 8, py - 24, 16, 4);
  ctx.fillStyle = "#f2c9a0";
  ctx.fillRect(px - 5, py - 32, 10, 9);
  ctx.fillStyle = opts.hair;
  ctx.fillRect(px - 5, py - 32, 10, 4);
}

function drawBubble(x, y, text) {
  ctx.font = "12px 'Microsoft YaHei', sans-serif";
  const width = Math.min(220, ctx.measureText(text).width + 16);
  const bx = Math.max(8, Math.min(canvas.width - width - 8, x - width / 2));
  const by = y - 52;
  ctx.fillStyle = "rgba(255,255,255,0.96)";
  ctx.strokeStyle = "#64748b";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(bx, by, width, 24, 5);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#1e293b";
  ctx.textAlign = "center";
  ctx.fillText(text, bx + width / 2, by + 17);
}

const stepLabels = {
  disease_onset: "发病",
  triage: "分诊",
  registration: "挂号",
  symptom_question: "护士追问",
  symptom_answer: "病人回答",
  consultation: "问诊",
  examination: "检查",
  diagnosis: "诊断",
  consultation_round: "会诊",
  consultation_summary: "主任仲裁",
  treatment: "开药",
  follow_up: "随访",
  end: "完成",
};

function labelFor(entry) {
  const stateName = entry.state;
  const payload = entry.payload || {};
  if (stateName === "triage") return `分诊 · ${payload.department || ""}`;
  if (stateName === "symptom_question") return `护士追问 · ${payload.question || ""}`;
  if (stateName === "symptom_answer") return `病人回答 · ${payload.text || ""}`;
  if (stateName === "consultation") return "问诊 · 开检查";
  if (stateName === "diagnosis") return `诊断 · ${payload.disease_name || ""}`;
  if (stateName === "consultation_round") return `会诊意见 · ${payload.disease_name || ""}`;
  if (stateName === "consultation_summary") return `主任仲裁 · ${payload.disease_name || ""}`;
  if (stateName === "treatment") return `开药 · ${(payload.treatment || []).join(" / ") || ""}`;
  return stepLabels[stateName] || stateName;
}

function activeRoles(entry) {
  if (entry.state === "triage" || entry.state === "registration" || entry.state === "examination") {
    return ["patient", "nurse"];
  }
  if (entry.state === "consultation" || entry.state === "diagnosis" || entry.state === "consultation_round" || entry.state === "consultation_summary") {
    return ["patient", "doctor"];
  }
  return ["patient"];
}

const roleMeta = {
  patient: { body: "#0e7490", hair: "#3f3f46" },
  nurse: { body: "#e2e8f0", hair: "#7c3aed", trim: "#c084fc" },
  doctor: { body: "#f8fafc", hair: "#475569", trim: "#38bdf8" },
};

function animateEpisode(result, speed) {
  const steps = result.transcript || [];
  $("eventLog").innerHTML = "";
  let patientPos = { ...stations.disease_onset };
  let stepIndex = 0;
  let active = true;

  function playStep() {
    if (!active) return;
    if (stepIndex >= steps.length) {
      showResult(result);
      return;
    }
    const entry = steps[stepIndex];
    const target = stations[entry.state] || stations.consultation;
    const roles = activeRoles(entry);
    const text = labelFor(entry);
    const li = document.createElement("li");
    li.className = entry.agent.includes("医生") ? "doctor" : entry.agent.includes("护士") ? "nurse" : "patient";
    li.textContent = text;
    $("eventLog").appendChild(li);
    $("eventLog").scrollTop = $("eventLog").scrollHeight;

    const duration = speed * 2.2;
    const start = { ...patientPos };
    const t0 = performance.now();

    function frame(now) {
      const t = Math.min(1, (now - t0) / duration);
      const eased = t < 1 ? t * t * (3 - 2 * t) : 1;
      patientPos.x = start.x + (target.x - start.x) * eased;
      patientPos.y = start.y + (target.y - start.y) * eased;
      drawHospital();
      if (roles.includes("patient")) drawPerson(patientPos.x, patientPos.y, roleMeta.patient);
      if (roles.includes("nurse")) drawPerson(target.x, target.y - 30, roleMeta.nurse);
      if (roles.includes("doctor")) drawPerson(target.x, target.y - 30, roleMeta.doctor);
      if (entry.state === "consultation_round") drawPerson(target.x + 26, target.y - 28, roleMeta.doctor);
      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        drawHospital();
        if (roles.includes("patient")) drawPerson(patientPos.x, patientPos.y, roleMeta.patient);
        if (roles.includes("nurse")) drawPerson(target.x, target.y - 30, roleMeta.nurse);
        if (roles.includes("doctor")) drawPerson(target.x, target.y - 30, roleMeta.doctor);
        if (entry.state === "consultation_round") drawPerson(target.x + 26, target.y - 28, roleMeta.doctor);
        drawBubble(target.x, target.y, text);
        stepIndex += 1;
        setTimeout(playStep, speed * 1.4);
      }
    }
    requestAnimationFrame(frame);
  }

  drawHospital();
  drawPerson(patientPos.x, patientPos.y, roleMeta.patient);
  setTimeout(playStep, speed);
}

function showResult(result) {
  const truth = $("truthBox");
  truth.classList.remove("hidden", "ok", "bad");
  truth.classList.add(result.correct ? "ok" : "bad");
  const reasonerLabel = result.reasoner === "llm" ? "DeepSeek" : "规则";
  truth.innerHTML = `
    <span class="reasoner">${reasonerLabel}${result.memory_used ? " · 记忆" : ""}${result.consultation_triggered ? " · 会诊" : ""}</span>
    <div class="truth-title">${result.correct ? "诊断正确" : "诊断错误"}</div>
    <div>预测：${escapeHtml(result.diagnosis.disease_name)}</div>
    <div>真实：${escapeHtml(result.ground_truth.disease_name)}</div>
    ${result.diagnosis.reasoning ? `<div class="truth-note">${escapeHtml(result.diagnosis.reasoning)}</div>` : ""}`;

  const detail = $("detailBox");
  detail.classList.remove("hidden");
  const exams = (result.exam_results || [])
    .map((exam) => `<li>${escapeHtml(exam.name)}：${escapeHtml(exam.findings)}</li>`)
    .join("");
  const treatments = (result.treatment || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  detail.innerHTML = `
    <h3>检查结果</h3><ul>${exams || "<li>未开检查</li>"}</ul>
    <h3>治疗方案</h3><ul>${treatments || "<li>无</li>"}</ul>
    ${result.consultation_triggered ? `<h3>会诊意见</h3><ul>${(result.opinions || []).map((o) => `<li>${escapeHtml(o.doctor)}：${escapeHtml(o.disease_name)}（权重 ${o.weight}）</li>`).join("")}</ul>` : ""}`;

  const chips = $("memoryChips");
  chips.innerHTML = "";
  chips.classList.remove("empty");
  if (!result.retrieved_cases.length && !result.retrieved_rules.length) {
    chips.classList.add("empty");
    chips.textContent = "无检索记忆";
    return;
  }
  result.retrieved_cases.forEach((c) => {
    const chip = document.createElement("span");
    chip.className = "chip case";
    chip.textContent = `案例 · ${c.diagnosis}`;
    chips.appendChild(chip);
  });
  result.retrieved_rules.forEach((r) => {
    const chip = document.createElement("span");
    chip.className = "chip rule";
    chip.textContent = `规则 · ${r.favor}`;
    chips.appendChild(chip);
  });
}

$("runBtn").addEventListener("click", async () => {
  $("runBtn").disabled = true;
  const speed = Number($("speedSelect").value);
  const body = {
    department: $("deptSelect").value || null,
    disease_id: $("diseaseSelect").value || null,
    use_memory: $("memoryToggle").checked,
    force_consultation: $("forceConsultation").checked,
    reasoner: $("modelSelect").value,
  };
  const result = await api("/api/episode/run", body);
  const info = $("patientInfo");
  info.classList.remove("empty");
  info.innerHTML = `
    <div class="name">${result.patient.name}</div>
    <div class="meta">${result.patient.gender === "male" ? "男" : "女"} · ${result.patient.age} 岁 · ${result.department}</div>
    <div class="symptom-tags">${result.patient.symptoms.map((s) => `<span class="tag">${s}</span>`).join("")}</div>`;
  $("truthBox").classList.add("hidden");
  $("detailBox").classList.add("hidden");
  $("memoryChips").innerHTML = "";
  $("memoryChips").classList.add("empty");
  $("memoryChips").textContent = "无";
  animateEpisode(result, speed);
  $("runBtn").disabled = false;
});

/* ---------- evolution view ---------- */
const chart = $("evChart");
const chartCtx = chart ? chart.getContext("2d") : null;
const variantColors = { A: "#64748b", B: "#0e7490", C: "#b45309", D: "#15803d" };

function drawChart(results) {
  if (!chartCtx) return;
  chartCtx.clearRect(0, 0, chart.width, chart.height);
  chartCtx.fillStyle = "#fbfcfe";
  chartCtx.fillRect(0, 0, chart.width, chart.height);
  const pad = { l: 46, r: 16, t: 18, b: 34 };
  const w = chart.width - pad.l - pad.r;
  const h = chart.height - pad.t - pad.b;
  let maxX = 1;
  let minY = 0.5;
  let maxY = 1.0;
  Object.values(results).forEach((r) => {
    maxX = Math.max(maxX, ...r.patients_treated);
    minY = Math.min(minY, ...r.accuracy);
    maxY = Math.max(maxY, ...r.accuracy);
  });
  minY = Math.max(0.4, Math.floor((minY - 0.05) * 10) / 10);
  maxY = Math.min(1.0, Math.ceil((maxY + 0.02) * 10) / 10);

  chartCtx.strokeStyle = "#e2e8f0";
  chartCtx.fillStyle = "#64748b";
  chartCtx.font = "11px sans-serif";
  for (let i = 0; i <= 5; i++) {
    const y = pad.t + h - (i / 5) * h;
    const value = minY + (maxY - minY) * (i / 5);
    chartCtx.beginPath();
    chartCtx.moveTo(pad.l, y);
    chartCtx.lineTo(pad.l + w, y);
    chartCtx.stroke();
    chartCtx.textAlign = "right";
    chartCtx.fillText(value.toFixed(2), pad.l - 6, y + 4);
  }
  chartCtx.fillText("Patients Treated", pad.l + w / 2 - 10, chart.height - 10);
  chartCtx.fillText("Test Accuracy", 16, pad.t + h / 2);

  Object.entries(results).forEach(([variant, r]) => {
    chartCtx.strokeStyle = variantColors[variant] || "#334155";
    chartCtx.lineWidth = 2;
    chartCtx.beginPath();
    r.patients_treated.forEach((x, i) => {
      const px = pad.l + (x / maxX) * w;
      const py = pad.t + h - ((r.accuracy[i] - minY) / (maxY - minY)) * h;
      if (i === 0) chartCtx.moveTo(px, py);
      else chartCtx.lineTo(px, py);
    });
    chartCtx.stroke();
    r.patients_treated.forEach((x, i) => {
      const px = pad.l + (x / maxX) * w;
      const py = pad.t + h - ((r.accuracy[i] - minY) / (maxY - minY)) * h;
      chartCtx.fillStyle = variantColors[variant] || "#334155";
      chartCtx.beginPath();
      chartCtx.arc(px, py, 3, 0, Math.PI * 2);
      chartCtx.fill();
    });
  });
}

function renderEvolutionTable(results) {
  const wrap = $("evTableWrap");
  const rows = Object.entries(results).map(([variant, r]) => {
    const totalCases = Object.values(r.case_counts).reduce((a, b) => a + b, 0);
    const totalRules = Object.values(r.rule_counts).reduce((a, b) => a + b, 0);
    const survivals = Object.values(r.rule_survival).filter((v) => v > 0);
    const avgSurvival = survivals.length ? survivals.reduce((a, b) => a + b, 0) / survivals.length : 0;
    return `
      <tr>
        <td><b>${variant}</b></td>
        <td class="num">${(r.initial_accuracy * 100).toFixed(1)}%</td>
        <td class="num">${(r.final_accuracy * 100).toFixed(1)}%</td>
        <td class="num">${totalCases}</td>
        <td class="num">${totalRules}</td>
        <td class="num">${(avgSurvival * 100).toFixed(1)}%</td>
      </tr>`;
  }).join("");
  wrap.innerHTML = `
    <table>
      <thead><tr><th>变体</th><th class="num">初始</th><th class="num">最终</th><th class="num">案例</th><th class="num">规则</th><th class="num">规则存活</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

/* ---------- memory view ---------- */
function renderMemory(results) {
  const wrap = $("memoryOverview");
  if (!results) {
    wrap.classList.remove("empty");
    wrap.classList.add("empty");
    wrap.textContent = "进化实验暂未启用";
    return;
  }
  const d = results.D || results.A;
  if (!d) return;
  const departments = Object.keys(d.case_counts);
  wrap.classList.remove("empty");
  wrap.classList.add("memory-grid");
  wrap.innerHTML = departments.map((dept) => `
    <div class="memory-card">
      <h4>${dept}</h4>
      <div class="stat"><span>案例</span><b>${d.case_counts[dept]}</b></div>
      <div class="stat"><span>规则</span><b>${d.rule_counts[dept]}</b></div>
      <div class="stat"><span>规则存活率</span><b>${(d.rule_survival[dept] * 100).toFixed(1)}%</b></div>
    </div>`).join("");
}

/* ---------- init ---------- */
drawHospital();
drawPerson(58, 290, roleMeta.patient);
loadKb();
