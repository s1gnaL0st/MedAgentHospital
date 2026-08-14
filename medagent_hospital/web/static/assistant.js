const STAGES = ["guide", "nurse", "doctor", "chief"];
const ROLE_LABELS = {
  guide: "导医",
  nurse: "护士",
  doctor: "主诊医师",
  chief: "主任医师",
  user: "医生",
};
const GENDER_LABELS = { male: "男", female: "女", any: "不限" };

let session = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let data = {};
  try {
    data = await response.json();
  } catch (_) {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || `请求失败 (${response.status})`);
  }
  return data;
}

function reset() {
  session = null;
  document.getElementById("startForm").style.display = "";
  document.getElementById("chatLog").replaceChildren();
  document.getElementById("actionArea").replaceChildren();
  const patientPanel = document.getElementById("patientPanel");
  patientPanel.textContent = "尚未开始会话";
  patientPanel.className = "muted empty";
  const suggestionPanel = document.getElementById("suggestionPanel");
  suggestionPanel.textContent = "等待角色建议";
  suggestionPanel.className = "muted empty";
  document.querySelectorAll("#stageList li").forEach((item) => {
    item.classList.remove("active", "done");
  });
  document.getElementById("startError").textContent = "";
}

function render(state) {
  renderStages(state);
  renderPatient(state);
  renderChat(state);
  renderSuggestion(state);
  renderActions(state);
}

function renderStages(state) {
  const currentIndex = state.done ? STAGES.length : STAGES.indexOf(state.stage);
  document.querySelectorAll("#stageList li").forEach((item) => {
    const index = STAGES.indexOf(item.dataset.stage);
    item.classList.toggle("active", index === currentIndex && !state.done);
    item.classList.toggle("done", state.done || index < currentIndex);
  });
}

function tagList(items) {
  const wrap = el("div", "chips");
  if (!items || !items.length) {
    wrap.appendChild(el("span", "muted", "无"));
    return wrap;
  }
  items.forEach((item) => wrap.appendChild(el("span", "tag", item)));
  return wrap;
}

function renderPatient(state) {
  const panel = document.getElementById("patientPanel");
  panel.replaceChildren();
  const patient = state.patient;
  const title = el("p", "patient-title", `${patient.name || "患者"} · ${patient.id}`);
  const meta = el(
    "p",
    "patient-line",
    `${GENDER_LABELS[patient.gender] || "不限"} / ${patient.age} 岁`
  );
  if (state.department) {
    meta.textContent += ` / ${state.department}`;
  }
  panel.append(title, meta);
  panel.appendChild(el("div", "suggestion-section"));
  panel.lastElementChild.appendChild(el("h3", "", "症状"));
  panel.lastElementChild.appendChild(tagList(patient.symptoms));
  if (patient.medical_history.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "既往史"));
    panel.lastElementChild.appendChild(tagList(patient.medical_history));
  }
  if (patient.risk_factors.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "危险因素"));
    panel.lastElementChild.appendChild(tagList(patient.risk_factors));
  }
}

function renderChat(state) {
  const log = document.getElementById("chatLog");
  log.replaceChildren();
  state.messages.forEach((message) => {
    const isUser = message.role === "user";
    const bubble = el("div", isUser ? "msg msg-user" : "msg msg-agent");
    if (!isUser) {
      bubble.appendChild(
        el("span", "msg-role", ROLE_LABELS[message.role] || message.role)
      );
    }
    bubble.appendChild(document.createTextNode(message.content));
    log.appendChild(bubble);
  });
  log.scrollTop = log.scrollHeight;
}

function section(title) {
  const wrap = el("div", "suggestion-section");
  wrap.appendChild(el("h3", "", title));
  return wrap;
}

function renderSuggestion(state) {
  const panel = document.getElementById("suggestionPanel");
  panel.replaceChildren();
  const suggestion = state.suggestion;
  if (state.done) {
    const last = state.messages[state.messages.length - 1];
    panel.appendChild(section("结论"));
    panel.lastElementChild.appendChild(el("p", "suggestion-text", last ? last.content : "已完成"));
    return;
  }
  if (!suggestion) {
    panel.appendChild(el("span", "muted", "等待角色建议"));
    return;
  }

  if (state.stage === "guide") {
    const head = section("导医建议");
    head.appendChild(
      el("p", "suggestion-text", `建议科室：${suggestion.department}（${suggestion.reason}）`)
    );
    panel.appendChild(head);
    const ranks = section("科室匹配");
    const maxMatched = Math.max(1, ...suggestion.departments.map((item) => item.matched));
    suggestion.departments.slice(0, 5).forEach((item) => {
      const row = el("div", "rank-row");
      row.appendChild(el("span", "", item.department));
      row.appendChild(el("span", "rank-score", `匹配 ${item.matched}`));
      const track = el("div", "score-track");
      const fill = el("div", "score-fill");
      fill.style.width = `${Math.round((item.matched / maxMatched) * 100)}%`;
      track.appendChild(fill);
      row.appendChild(track);
      ranks.appendChild(row);
    });
    panel.appendChild(ranks);
    return;
  }

  if (state.stage === "nurse") {
    const head = section("护士追问");
    head.appendChild(
      el(
        "p",
        "suggestion-text",
        `问题 ${suggestion.question_index}/${suggestion.total}：${suggestion.question}`
      )
    );
    panel.appendChild(head);
    return;
  }

  if (state.stage === "doctor") {
    const head = section("鉴别诊断");
    head.appendChild(el("p", "suggestion-text", suggestion.reasoning));
    panel.appendChild(head);
    const ranks = section("候选排序");
    const maxScore = Math.max(
      0.0001,
      ...suggestion.candidates.map((item) => item.score)
    );
    suggestion.candidates.forEach((item) => {
      const row = el("div", "rank-row");
      row.appendChild(el("span", "", item.disease_name));
      row.appendChild(el("span", "rank-score", item.score.toFixed(2)));
      const track = el("div", "score-track");
      const fill = el("div", "score-fill");
      fill.style.width = `${Math.round((item.score / maxScore) * 100)}%`;
      track.appendChild(fill);
      row.appendChild(track);
      ranks.appendChild(row);
    });
    panel.appendChild(ranks);
    if (suggestion.exams.length) {
      panel.appendChild(section("建议检查"));
      panel.lastElementChild.appendChild(tagList(suggestion.exams));
    }
    if (suggestion.treatment.length) {
      panel.appendChild(section("治疗参考"));
      panel.lastElementChild.appendChild(tagList(suggestion.treatment));
    }
    const memory = [];
    suggestion.retrieved_cases.forEach((item) =>
      memory.push(`${item.diagnosis} (${item.score})`)
    );
    suggestion.retrieved_rules.forEach((item) => memory.push(item.rule));
    panel.appendChild(section("检索记忆"));
    panel.lastElementChild.appendChild(tagList(memory));
    return;
  }

  if (state.stage === "chief") {
    panel.appendChild(section("主任复核"));
    panel.lastElementChild.appendChild(
      el("p", "suggestion-text", suggestion.summary)
    );
    panel.appendChild(section("最终诊断"));
    panel.lastElementChild.appendChild(
      el("p", "suggestion-text", suggestion.diagnosis_name || "待定")
    );
    if (suggestion.treatment.length) {
      panel.appendChild(section("治疗方案"));
      panel.lastElementChild.appendChild(tagList(suggestion.treatment));
    }
    panel.appendChild(section("随访建议"));
    panel.lastElementChild.appendChild(tagList(suggestion.follow_up));
  }
}

function setBusy(buttons, busy) {
  buttons.forEach((button) => {
    button.disabled = busy;
  });
}

async function runAction(promise, buttons) {
  setBusy(buttons, true);
  try {
    session = await promise;
    render(session);
  } catch (error) {
    const area = document.getElementById("actionArea");
    area.appendChild(el("div", "form-error", error.message));
  } finally {
    setBusy(buttons, false);
  }
}

function renderActions(state) {
  const area = document.getElementById("actionArea");
  area.replaceChildren();
  if (state.done) return;

  const row = el("div", "action-row");
  if (state.stage === "guide") {
    const select = el("select", "", "");
    (state.suggestion.departments || []).forEach((item) => {
      const option = el("option", "", item.department);
      option.value = item.department;
      if (item.department === state.suggestion.department) option.selected = true;
      select.appendChild(option);
    });
    const confirm = el("button", "btn primary", "确认分诊");
    confirm.type = "button";
    confirm.addEventListener("click", () => {
      runAction(
        api("/api/assistant/confirm", {
          method: "POST",
          body: { session_id: state.session_id, stage: "guide", accepted: true, override: select.value },
        }),
        [confirm]
      );
    });
    row.append(select, confirm);
  }

  if (state.stage === "nurse") {
    const question = state.suggestion.question;
    row.appendChild(el("div", "action-question", `${question}？`));
    const yes = el("button", "btn primary", "有");
    const no = el("button", "btn ghost", "没有");
    const skip = el("button", "btn ghost", "跳过追问");
    yes.type = no.type = skip.type = "button";
    yes.addEventListener("click", () => {
      runAction(
        api("/api/assistant/answer", {
          method: "POST",
          body: { session_id: state.session_id, symptom: question, present: true },
        }),
        [yes, no, skip]
      );
    });
    no.addEventListener("click", () => {
      runAction(
        api("/api/assistant/answer", {
          method: "POST",
          body: { session_id: state.session_id, symptom: question, present: false },
        }),
        [yes, no, skip]
      );
    });
    skip.addEventListener("click", () => {
      runAction(
        api("/api/assistant/confirm", {
          method: "POST",
          body: { session_id: state.session_id, stage: "nurse", accepted: true },
        }),
        [yes, no, skip]
      );
    });
    row.append(yes, no, skip);
  }

  if (state.stage === "doctor") {
    const select = el("select", "", "");
    (state.suggestion.candidates || []).forEach((item) => {
      const option = el("option", "", `${item.disease_name} (${item.score.toFixed(2)})`);
      option.value = item.disease_id;
      if (item.disease_id === state.suggestion.best_id) option.selected = true;
      select.appendChild(option);
    });
    const confirm = el("button", "btn primary", "确认诊断");
    confirm.type = "button";
    confirm.addEventListener("click", () => {
      runAction(
        api("/api/assistant/confirm", {
          method: "POST",
          body: { session_id: state.session_id, stage: "doctor", accepted: true, override: select.value },
        }),
        [confirm]
      );
    });
    row.append(select, confirm);
  }

  if (state.stage === "chief") {
    const confirm = el("button", "btn primary", "确认最终方案");
    confirm.type = "button";
    confirm.addEventListener("click", () => {
      runAction(
        api("/api/assistant/confirm", {
          method: "POST",
          body: { session_id: state.session_id, stage: "chief", accepted: true },
        }),
        [confirm]
      );
    });
    row.appendChild(confirm);
  }
  area.appendChild(row);
}

document.getElementById("startForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  document.getElementById("startError").textContent = "";
  const body = {
    gender: document.getElementById("genderInput").value,
    age: Number(document.getElementById("ageInput").value) || 45,
    symptoms: document.getElementById("symptomsInput").value,
    medical_history: document.getElementById("historyInput").value,
    risk_factors: document.getElementById("riskInput").value,
  };
  if (!body.symptoms.trim()) {
    document.getElementById("startError").textContent = "请至少输入一个症状";
    return;
  }
  const startBtn = document.getElementById("startBtn");
  startBtn.disabled = true;
  try {
    const state = await api("/api/assistant/start", { method: "POST", body });
    session = state;
    document.getElementById("startForm").style.display = "none";
    render(state);
  } catch (error) {
    document.getElementById("startError").textContent = error.message;
  } finally {
    startBtn.disabled = false;
  }
});

document.getElementById("newSessionBtn").addEventListener("click", reset);
reset();
