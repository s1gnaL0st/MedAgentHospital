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
    if (!tab.dataset.view) return;
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
  disease_onset: { x: 45, y: 280 },
  triage: { x: 240, y: 128 },
  registration: { x: 240, y: 438 },
  symptom_question: { x: 720, y: 128 },
  symptom_answer: { x: 720, y: 128 },
  consultation: { x: 720, y: 128 },
  examination: { x: 480, y: 438 },
  diagnosis: { x: 720, y: 128 },
  consultation_round: { x: 720, y: 128 },
  consultation_summary: { x: 720, y: 128 },
  treatment: { x: 720, y: 438 },
  follow_up: { x: 915, y: 280 },
  end: { x: 915, y: 280 },
};

const rooms = [
  { name: "分诊台", x: 120, y: 80, w: 240, h: 90 },
  { name: "候诊区", x: 360, y: 80, w: 240, h: 90 },
  { name: "诊室", x: 600, y: 80, w: 240, h: 90 },
  { name: "挂号处", x: 120, y: 390, w: 240, h: 90 },
  { name: "检查室", x: 360, y: 390, w: 240, h: 90 },
  { name: "药房", x: 600, y: 390, w: 240, h: 90 },
];

const woodTiles = ["#a97c4f", "#9b7047", "#b3875a", "#8f6540", "#a2754c"];

function pickWood(x, y) {
  return woodTiles[(x * 7 + y * 13) % woodTiles.length];
}

function drawHospital() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // grass outside
  ctx.fillStyle = "#4c9a48";
  ctx.fillRect(0, 0, canvas.width, 40);
  ctx.fillStyle = "#4c9a48";
  ctx.fillRect(0, 40, canvas.width, canvas.height - 40);
  ctx.fillStyle = "#3d843d";
  for (let y = 8; y < 528; y += 18) {
    for (let x = 8; x < 950; x += 22) {
      if ((x + y) % 5 === 0) ctx.fillRect(x, y, 4, 4);
    }
  }
  const flowers = [[18, 12], [52, 26], [86, 8], [130, 20], [836, 12], [900, 24], [930, 16], [26, 470], [920, 500]];
  flowers.forEach(([fx, fy]) => {
    ctx.fillStyle = fx % 2 ? "#fde047" : "#ffffff";
    ctx.fillRect(fx, fy, 5, 5);
    ctx.fillStyle = "#f97316";
    ctx.fillRect(fx + 1, fy + 1, 3, 3);
  });

  // trees outside
  [[34, 28], [926, 28], [34, 512], [926, 512]].forEach(([tx, ty]) => {
    ctx.fillStyle = "#5b3a29";
    ctx.fillRect(tx - 3, ty - 8, 6, 12);
    ctx.fillStyle = "#2f7d32";
    ctx.beginPath();
    ctx.arc(tx, ty - 14, 14, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#3f9b42";
    ctx.beginPath();
    ctx.arc(tx - 6, ty - 18, 8, 0, Math.PI * 2);
    ctx.fill();
  });

  // 3D walls with openings at the corridor ends
  function wall(x, y, w, h) {
    ctx.fillStyle = "#4a2f1d";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "#8a6240";
    ctx.fillRect(x, y, w, 5);
    ctx.fillStyle = "#6b4a2f";
    ctx.fillRect(x, y + 5, w, h - 5);
    ctx.strokeStyle = "rgba(42,25,12,0.35)";
    ctx.lineWidth = 1;
    for (let yy = y + 12; yy < y + h; yy += 12) {
      ctx.beginPath();
      ctx.moveTo(x, yy);
      ctx.lineTo(x + w, yy);
      ctx.stroke();
    }
    for (let xx = x + 12; xx < x + w; xx += 12) {
      ctx.beginPath();
      ctx.moveTo(xx, y + 5);
      ctx.lineTo(xx, y + h);
      ctx.stroke();
    }
  }
  wall(70, 56, 820, 18);
  wall(70, 486, 820, 18);
  wall(70, 56, 18, 134);
  wall(70, 370, 18, 130);
  wall(872, 56, 18, 134);
  wall(872, 370, 18, 130);

  // interior wood floor
  for (let y = 74; y < 486; y += 12) {
    for (let x = 88; x < 872; x += 12) {
      ctx.fillStyle = pickWood(x, y);
      ctx.fillRect(x, y, 12, 12);
    }
  }
  ctx.strokeStyle = "rgba(63,40,25,0.35)";
  ctx.lineWidth = 1;
  for (let y = 74; y <= 486; y += 12) {
    ctx.beginPath();
    ctx.moveTo(88, y);
    ctx.lineTo(872, y);
    ctx.stroke();
  }

  // corridor stripes
  const corridorColors = ["#5a3a22", "#6b4527"];
  for (let y = 190; y < 370; y += 24) {
    ctx.fillStyle = corridorColors[Math.floor(y / 24) % 2];
    ctx.fillRect(88, y, 784, 24);
  }
  ctx.strokeStyle = "rgba(42,25,12,0.45)";
  ctx.lineWidth = 1;
  for (let x = 88; x < 872; x += 48) {
    ctx.beginPath();
    ctx.moveTo(x, 190);
    ctx.lineTo(x, 370);
    ctx.stroke();
  }
  ctx.fillStyle = "#3a2415";
  ctx.fillRect(88, 186, 784, 4);
  ctx.fillRect(88, 368, 784, 4);

  // sign
  ctx.fillStyle = "#3f2819";
  ctx.fillRect(392, 10, 176, 34);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(400, 16, 160, 14);
  drawCross(430, 23, 10, "#dc2626");
  ctx.fillStyle = "#1f2937";
  ctx.font = "12px 'Microsoft YaHei', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("医院", 476, 26);

  const wallColors = ["#0e7490", "#b45309", "#7c3aed", "#0e7490", "#b45309", "#7c3aed"];
  rooms.forEach((room, index) => {
    ctx.fillStyle = "#e2cba4";
    ctx.fillRect(room.x, room.y, room.w, room.h);
    ctx.strokeStyle = "#5b3a29";
    ctx.lineWidth = 4;
    ctx.strokeRect(room.x, room.y, room.w, room.h);
    ctx.fillStyle = wallColors[index % wallColors.length];
    ctx.fillRect(room.x, room.y, room.w, 6);
    ctx.fillStyle = "rgba(255,255,255,0.45)";
    for (let x = room.x + 10; x < room.x + room.w - 6; x += 16) {
      ctx.fillRect(x, room.y + 1, 4, 4);
    }
    ctx.strokeStyle = "rgba(91,58,41,0.30)";
    ctx.lineWidth = 1;
    for (let y = room.y + 10; y < room.y + room.h; y += 8) {
      ctx.beginPath();
      ctx.moveTo(room.x + 2, y);
      ctx.lineTo(room.x + room.w - 2, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#8b5a2b";
    ctx.fillRect(room.x + room.w / 2 - 11, room.y + room.h - 10, 22, 8);
    ctx.fillStyle = "#5b3a29";
    ctx.fillRect(room.x + room.w / 2 + 2, room.y + room.h - 8, 3, 4);
  });

  // 分诊台 / 挂号处
  drawDesk(128, 126, 80, 12);
  drawMonitor(168, 126);
  drawStool(140, 146);
  drawStool(200, 146);
  drawDesk(128, 430, 80, 12);
  drawMonitor(168, 430);
  drawStool(140, 450);
  drawStool(200, 450);

  // 诊室
  drawBed(760, 86, 60, 18);
  drawDesk(616, 140, 64, 10);
  drawMonitor(648, 140);
  drawStool(648, 154);

  // 检查室
  drawBed(520, 430, 60, 18);
  drawDesk(406, 452, 60, 8);
  drawMonitor(436, 448);
  drawStool(436, 466);

  // 药房
  drawShelves(616, 394, 140);
  drawDesk(636, 442, 48, 10);
  drawMonitor(660, 442);
  drawStool(676, 458);

  // 候诊区
  drawRug(390, 100, 180, 50);
  [[410, 110], [436, 110], [462, 110], [410, 140], [436, 140], [462, 140]].forEach(([sx, sy]) => drawStool(sx, sy));

  // decor: flower pots, medical kits, TV
  drawFlowerPot(306, 148);
  drawMedicalKit(306, 120);
  drawFlowerPot(306, 458);
  drawMedicalKit(306, 430);
  drawTV(800, 404);
  drawFlowerPot(760, 160);
  drawMedicalKit(546, 404);
  drawFlowerPot(570, 470);
  drawFlowerPot(776, 404);
  drawMedicalKit(776, 470);
  drawTV(580, 96);

  // banners and torches
  drawBanner(84, 280);
  drawBanner(872, 280);
  const torchSpots = [[84, 64], [300, 64], [600, 64], [872, 64], [84, 500], [300, 500], [600, 500], [872, 500]];
  torchSpots.forEach(([tx, ty]) => drawTorch(tx, ty));

  rooms.forEach((room) => {
    ctx.fillStyle = "#2f2318";
    ctx.font = "12px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(room.name, room.x + room.w / 2, room.y + 18);
  });

  ctx.fillStyle = "#f7ecd8";
  ctx.font = "11px 'Microsoft YaHei', sans-serif";
  ctx.fillText("MedAgent-Hospital · 仿真医院", 478, 528);
}

function drawDesk(x, y, w, h) {
  ctx.fillStyle = "rgba(20,12,6,0.28)";
  ctx.fillRect(x + 3, y + 3, w, h);
  ctx.fillStyle = "#7c5a3a";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#b58a58";
  ctx.fillRect(x, y, w, 4);
  ctx.fillStyle = "#a97c4f";
  ctx.fillRect(x, y + 4, w, h - 6);
  ctx.fillStyle = "#5a3c24";
  ctx.fillRect(x, y + h - 3, w, 3);
}

function drawDeskVertical(x, y, w, h) {
  ctx.fillStyle = "rgba(20,12,6,0.28)";
  ctx.fillRect(x + 3, y + 3, w, h);
  ctx.fillStyle = "#7c5a3a";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#b58a58";
  ctx.fillRect(x, y, w, 4);
  ctx.fillStyle = "#a97c4f";
  ctx.fillRect(x, y + 4, w, h - 4);
  ctx.fillStyle = "#5a3c24";
  ctx.fillRect(x, y + h - 3, w, 3);
}

function drawMonitor(x, y) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x - 7, y - 6, 15, 12);
  ctx.fillStyle = "#334155";
  ctx.fillRect(x - 7, y - 9, 14, 10);
  ctx.fillStyle = "#1f2937";
  ctx.fillRect(x - 6, y - 8, 12, 8);
  ctx.fillStyle = "#38bdf8";
  ctx.fillRect(x - 5, y - 7, 10, 6);
  ctx.fillStyle = "rgba(255,255,255,0.28)";
  ctx.fillRect(x - 5, y - 7, 10, 2);
  ctx.fillStyle = "#334155";
  ctx.fillRect(x - 1, y, 2, 3);
  ctx.fillRect(x - 4, y + 3, 8, 2);
  ctx.fillStyle = "#1f2937";
  ctx.fillRect(x - 4, y + 5, 8, 2);
}

function drawBed(x, y, w, h) {
  ctx.fillStyle = "rgba(20,12,6,0.28)";
  ctx.fillRect(x + 3, y + 3, w, h);
  ctx.fillStyle = "#6b4527";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#8b5a2b";
  ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x + 3, y + 3, 20, h - 6);
  ctx.fillStyle = "#0e7490";
  ctx.fillRect(x + 25, y + 3, w - 28, h - 6);
  ctx.fillStyle = "rgba(255,255,255,0.25)";
  ctx.fillRect(x + 25, y + 3, w - 28, 3);
  ctx.fillStyle = "#3f2819";
  ctx.fillRect(x + 3, y + h - 2, 4, 4);
  ctx.fillRect(x + 14, y + h - 2, 4, 4);
  ctx.fillRect(x + w - 7, y + h - 2, 4, 4);
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x + 3, y + h - 5, 4, 3);
  ctx.fillRect(x + 14, y + h - 5, 4, 3);
  ctx.fillRect(x + w - 7, y + h - 5, 4, 3);
}

function drawBedV(x, y, w, h) {
  ctx.fillStyle = "rgba(20,12,6,0.28)";
  ctx.fillRect(x + 3, y + 3, w, h);
  ctx.fillStyle = "#6b4527";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#8b5a2b";
  ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x + 3, y + 3, w - 6, 12);
  ctx.fillStyle = "#0e7490";
  ctx.fillRect(x + 3, y + 15, w - 6, h - 18);
  ctx.fillStyle = "rgba(255,255,255,0.25)";
  ctx.fillRect(x + 3, y + 15, w - 6, 3);
}

function drawShelves(x, y, w) {
  ctx.fillStyle = "rgba(20,12,6,0.28)";
  ctx.fillRect(x + 10, y + 17, w - 16, 14);
  ctx.fillStyle = "#7c5a3a";
  ctx.fillRect(x + 8, y + 14, w - 16, 14);
  ctx.fillStyle = "#a97c4f";
  ctx.fillRect(x + 8, y + 14, w - 16, 3);
  const itemColors = ["#e11d48", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#f97316"];
  for (let i = 0; i < 6; i++) {
    ctx.fillStyle = itemColors[i];
    ctx.fillRect(x + 14 + i * 16, y + 18, 8, 8);
    ctx.fillStyle = "rgba(255,255,255,0.30)";
    ctx.fillRect(x + 14 + i * 16, y + 18, 8, 2);
  }
}

function drawStool(x, y) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x - 2, y + 2, 8, 8);
  ctx.fillStyle = "#6d28d9";
  ctx.fillRect(x - 4, y, 8, 8);
  ctx.fillStyle = "#8b5cf6";
  ctx.fillRect(x - 4, y, 8, 4);
  ctx.fillStyle = "#4c1d95";
  ctx.fillRect(x - 4, y + 6, 8, 2);
}

function drawFlowerPot(x, y) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x - 4, y + 2, 10, 8);
  ctx.fillStyle = "#78350f";
  ctx.fillRect(x - 5, y, 10, 8);
  ctx.fillStyle = "#b45309";
  ctx.fillRect(x - 5, y, 10, 4);
  ctx.fillStyle = "#92400e";
  ctx.fillRect(x + 2, y + 4, 3, 4);
  ctx.fillStyle = "#16a34a";
  ctx.fillRect(x - 1, y - 6, 2, 7);
  ctx.fillRect(x - 6, y - 3, 3, 5);
  ctx.fillRect(x + 3, y - 3, 3, 5);
  ctx.fillStyle = "#f43f5e";
  ctx.fillRect(x - 1, y - 8, 3, 3);
}

function drawMedicalKit(x, y) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x - 6, y + 2, 16, 12);
  ctx.fillStyle = "#e8eef2";
  ctx.fillRect(x - 8, y, 16, 12);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x - 8, y, 16, 4);
  ctx.strokeStyle = "#475569";
  ctx.lineWidth = 1;
  ctx.strokeRect(x - 8, y, 16, 12);
  drawCross(x, y + 6, 7, "#dc2626");
}

function drawTV(x, y) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x - 8, y + 2, 20, 14);
  ctx.fillStyle = "#1f2937";
  ctx.fillRect(x - 10, y, 20, 14);
  ctx.fillStyle = "#38bdf8";
  ctx.fillRect(x - 8, y + 2, 16, 9);
  ctx.fillStyle = "rgba(255,255,255,0.30)";
  ctx.fillRect(x - 8, y + 2, 16, 2);
  ctx.fillStyle = "#0f172a";
  ctx.fillRect(x - 1, y + 14, 2, 5);
  ctx.fillRect(x - 7, y + 19, 16, 3);
  ctx.fillStyle = "#334155";
  ctx.fillRect(x - 7, y + 22, 16, 2);
}

function drawBench(x, y, w) {
  ctx.fillStyle = "rgba(20,12,6,0.25)";
  ctx.fillRect(x + 2, y + 3, w, 10);
  ctx.fillStyle = "#78350f";
  ctx.fillRect(x, y, w, 10);
  ctx.fillStyle = "#b45309";
  ctx.fillRect(x, y, w, 4);
  ctx.fillStyle = "#451a03";
  ctx.fillRect(x, y + 10, w, 3);
  ctx.fillRect(x + 8, y + 13, 4, 4);
  ctx.fillRect(x + w - 12, y + 13, 4, 4);
}

function drawRug(x, y, w, h) {
  ctx.fillStyle = "rgba(20,12,6,0.20)";
  ctx.fillRect(x + 2, y + 2, w, h);
  ctx.fillStyle = "#0f766e";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#14b8a6";
  ctx.fillRect(x + 6, y + 6, w - 12, h - 12);
  ctx.strokeStyle = "#0b4f4a";
  ctx.lineWidth = 2;
  ctx.strokeRect(x + 3, y + 3, w - 6, h - 6);
  ctx.strokeStyle = "rgba(255,255,255,0.15)";
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 10, y + 10, w - 20, h - 20);
}

function drawTorch(x, y) {
  ctx.fillStyle = "rgba(255,180,60,0.18)";
  ctx.fillRect(x - 12, y - 12, 24, 24);
  ctx.fillStyle = "rgba(255,200,80,0.30)";
  ctx.fillRect(x - 8, y - 8, 16, 16);
  ctx.fillStyle = "#6b4226";
  ctx.fillRect(x - 2, y - 2, 4, 10);
  ctx.fillStyle = "#f97316";
  ctx.fillRect(x - 3, y - 7, 6, 6);
  ctx.fillStyle = "#fde047";
  ctx.fillRect(x - 1, y - 5, 2, 3);
}

function drawBanner(x, y) {
  ctx.fillStyle = "#3f2819";
  ctx.fillRect(x - 1, y, 3, 14);
  ctx.fillStyle = "#dc2626";
  ctx.fillRect(x + 2, y + 2, 10, 8);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x + 3, y + 4, 3, 3);
}

function drawCross(cx, cy, size, color) {
  const thickness = Math.max(2, Math.round(size / 3));
  ctx.fillStyle = color;
  ctx.fillRect(cx - size / 2, cy - thickness / 2, size, thickness);
  ctx.fillRect(cx - thickness / 2, cy - size / 2, thickness, size);
}

function drawPerson(x, y, opts) {
  const px = Math.round(x);
  const py = Math.round(y);
  ctx.fillStyle = "rgba(15, 23, 42, 0.22)";
  ctx.beginPath();
  ctx.ellipse(px, py - 1, 13, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = opts.body;
  ctx.beginPath();
  ctx.ellipse(px, py - 12, 12, 10, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = opts.trim || opts.body;
  ctx.beginPath();
  ctx.ellipse(px, py - 13, 9, 6, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = opts.hair;
  ctx.beginPath();
  ctx.arc(px, py - 27, 9, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#f5cba7";
  ctx.beginPath();
  ctx.arc(px, py - 28, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#1f2937";
  ctx.fillRect(px - 4, py - 29, 2, 3);
  ctx.fillRect(px + 2, py - 29, 2, 3);

  if (opts.role === "nurse") {
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(px, py - 36, 7, 0, Math.PI * 2);
    ctx.fill();
    drawCross(px, py - 36, 6, "#dc2626");
  } else if (opts.role === "guide") {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(px - 4, py - 18, 7, 9);
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 1;
    ctx.strokeRect(px - 4, py - 18, 7, 9);
    ctx.fillStyle = "#334155";
    ctx.fillRect(px - 3, py - 15, 5, 1);
    ctx.fillRect(px - 3, py - 12, 5, 1);
  } else if (opts.role === "doctor") {
    ctx.fillStyle = "#0e7490";
    ctx.fillRect(px + 2, py - 14, 3, 3);
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(px, py - 27, 10, -1.2, 1.2);
    ctx.stroke();
  }
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
  if (stateName === "triage") return `导医分诊 · ${payload.department || ""}`;
  if (stateName === "symptom_question") return `医生追问 · ${payload.question || ""}`;
  if (stateName === "symptom_answer") return `病人回答 · ${payload.text || ""}`;
  if (stateName === "consultation") return "问诊 · 开检查";
  if (stateName === "diagnosis") return `诊断 · ${payload.disease_name || ""}`;
  if (stateName === "consultation_round") return `会诊意见 · ${payload.disease_name || ""}`;
  if (stateName === "consultation_summary") return `主任仲裁 · ${payload.disease_name || ""}`;
  if (stateName === "treatment") return `开药 · ${(payload.treatment || []).join(" / ") || ""}`;
  return stepLabels[stateName] || stateName;
}

function activeRoles(entry) {
  if (entry.state === "triage") {
    return ["patient", "guide"];
  }
  if (
    entry.state === "registration" ||
    entry.state === "examination" ||
    entry.state === "treatment"
  ) {
    return ["patient", "nurse"];
  }
  if (entry.state === "symptom_question" || entry.state === "symptom_answer" || entry.state === "consultation" || entry.state === "diagnosis" || entry.state === "consultation_round" || entry.state === "consultation_summary") {
    return ["patient", "doctor"];
  }
  return ["patient"];
}

const roleMeta = {
  patient: { role: "patient", body: "#0e7490", hair: "#3f3f46", pants: "#475569" },
  nurse: { role: "nurse", body: "#e8f0f5", hair: "#7c3aed", trim: "#f472b6", pants: "#5b6b7b" },
  doctor: { role: "doctor", body: "#f8fafc", hair: "#475569", trim: "#38bdf8", pants: "#1f2937" },
  guide: { role: "guide", body: "#fbbf24", hair: "#1f2937", trim: "#f59e0b", pants: "#78350f" },
};

let currentAnimation = null;

function animateEpisode(result, speed) {
  const steps = result.transcript || [];
  $("eventLog").innerHTML = "";
  let patientPos = { ...stations.disease_onset };
  let stepIndex = 0;
  const token = { active: true };
  currentAnimation = token;

  function playStep() {
    if (!token.active) return;
    if (stepIndex >= steps.length) {
      if (currentAnimation === token) currentAnimation = null;
      showResult(result);
      return;
    }
    const entry = steps[stepIndex];
    const target = stations[entry.state] || stations.consultation;
    const roles = activeRoles(entry);
    const text = labelFor(entry);
    const li = document.createElement("li");
    li.className = entry.agent.includes("医生")
      ? "doctor"
      : entry.agent.includes("护士") || entry.agent.includes("导医")
        ? "nurse"
        : "patient";
    li.textContent = text;
    $("eventLog").appendChild(li);
    $("eventLog").scrollTop = $("eventLog").scrollHeight;

    const duration = speed * 2.2;
    const start = { ...patientPos };
    const t0 = performance.now();

    function frame(now) {
      if (!token.active) return;
      const t = Math.min(1, (now - t0) / duration);
      const eased = t < 1 ? t * t * (3 - 2 * t) : 1;
      patientPos.x = start.x + (target.x - start.x) * eased;
      patientPos.y = start.y + (target.y - start.y) * eased;
      drawHospital();
      if (roles.includes("patient")) drawPerson(patientPos.x, patientPos.y, roleMeta.patient);
      if (roles.includes("nurse")) drawPerson(target.x, target.y - 30, roleMeta.nurse);
      if (roles.includes("guide")) drawPerson(target.x, target.y - 30, roleMeta.guide);
      if (roles.includes("doctor")) drawPerson(target.x, target.y - 30, roleMeta.doctor);
      if (entry.state === "consultation_round") drawPerson(target.x + 26, target.y - 28, roleMeta.doctor);
      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        drawHospital();
        if (roles.includes("patient")) drawPerson(patientPos.x, patientPos.y, roleMeta.patient);
        if (roles.includes("nurse")) drawPerson(target.x, target.y - 30, roleMeta.nurse);
        if (roles.includes("guide")) drawPerson(target.x, target.y - 30, roleMeta.guide);
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
    <h3>导医记忆</h3><ul><li>案例 ${result.guide?.cases ?? 0}</li><li>规则 ${result.guide?.rules ?? 0}</li></ul>
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
  if (currentAnimation) {
    currentAnimation.active = false;
    currentAnimation = null;
  }
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
