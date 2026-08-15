const AGENT_LABELS = {
  guide: "导医",
  doctor: "主诊医生",
  chief: "主任医师",
  system: "系统",
  user: "我",
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

function bindDictation(input, button, onError) {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    button.textContent = "不支持";
    return;
  }
  let recognition = null;
  button.addEventListener("click", () => {
    if (recognition) {
      recognition.stop();
      recognition = null;
      button.textContent = "语音转文字";
      return;
    }
    recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.onstart = () => {
      button.textContent = "停止识别";
    };
    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join("");
      input.value = text;
    };
    recognition.onerror = (event) => {
      const message =
        event.error === "not-allowed"
          ? "未授权麦克风"
          : event.error === "no-speech"
            ? "未识别到语音"
            : "识别失败，请重试";
      if (onError) onError(message);
      button.textContent = message;
      recognition = null;
      setTimeout(() => {
        button.textContent = "语音转文字";
      }, 1500);
    };
    recognition.onend = () => {
      if (recognition) {
        recognition = null;
        button.textContent = "语音转文字";
      }
    };
    recognition.start();
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

function reset() {
  session = null;
  document.getElementById("startForm").style.display = "";
  document.getElementById("chatLog").replaceChildren();
  document.getElementById("patientPanel").textContent = "尚未开始问诊";
  document.getElementById("patientPanel").className = "muted empty";
  document.getElementById("handoffPanel").textContent = "暂无";
  document.getElementById("handoffPanel").className = "muted empty";
  document.getElementById("orderPanel").textContent = "尚未开单";
  document.getElementById("orderPanel").className = "muted empty";
  const badge = document.getElementById("agentBadge");
  badge.textContent = "当前接诊：导医";
  badge.classList.remove("done-badge");
  document.getElementById("startError").textContent = "";
  document.getElementById("chatInput").value = "";
}

function render(state) {
  session = state;
  renderBadge(state);
  renderMessages(state);
  renderPatient(state);
  renderHandoffs(state);
  renderOrders(state);
}

function renderBadge(state) {
  const badge = document.getElementById("agentBadge");
  if (state.done) {
    badge.textContent = "就诊完成";
    badge.classList.add("done-badge");
    return;
  }
  badge.textContent = `当前接诊：${AGENT_LABELS[state.current_agent] || state.current_agent}`;
  badge.classList.remove("done-badge");
}

function renderMessages(state) {
  const log = document.getElementById("chatLog");
  log.replaceChildren();
  state.messages.forEach((message) => {
    if (message.sender === "system") {
      log.appendChild(el("div", "msg msg-system", message.content));
      return;
    }
    const isUser = message.sender === "user";
    const bubble = el("div", isUser ? "msg msg-user" : "msg msg-agent");
    if (!isUser) {
      bubble.appendChild(
        el("span", "msg-role", AGENT_LABELS[message.sender] || message.sender)
      );
    }
    bubble.appendChild(document.createTextNode(message.content));
    log.appendChild(bubble);
  });
  log.scrollTop = log.scrollHeight;
}

function renderPatient(state) {
  const panel = document.getElementById("patientPanel");
  panel.replaceChildren();
  const patient = state.patient;
  panel.appendChild(
    el("p", "patient-title", `${patient.name || "患者"} · ${patient.id}`)
  );
  const meta = el(
    "p",
    "patient-line",
    `${GENDER_LABELS[patient.gender] || "不限"} / ${patient.age} 岁`
  );
  if (state.department) meta.textContent += ` / ${state.department}`;
  panel.appendChild(meta);
  panel.appendChild(el("div", "suggestion-section"));
  panel.lastElementChild.appendChild(el("h3", "", "症状"));
  panel.lastElementChild.appendChild(tagList(patient.symptoms));
}

function renderHandoffs(state) {
  const panel = document.getElementById("handoffPanel");
  panel.replaceChildren();
  if (!state.handoffs || !state.handoffs.length) {
    panel.appendChild(el("span", "muted", "暂无"));
    return;
  }
  state.handoffs.forEach((handoff) => {
    panel.appendChild(
      el(
        "p",
        "suggestion-text",
        `${AGENT_LABELS[handoff.from] || handoff.from} → ${AGENT_LABELS[handoff.to] || handoff.to}（${handoff.reason}）`
      )
    );
  });
}

function renderOrders(state) {
  const panel = document.getElementById("orderPanel");
  panel.replaceChildren();
  const orders = state.orders || [];
  const reports = state.reports || [];
  if (!orders.length && !reports.length) {
    panel.appendChild(el("span", "muted", "尚未开单"));
    return;
  }
  const exams = orders.filter((item) => item.kind === "exam");
  const medications = orders.filter((item) => item.kind === "medication");
  if (exams.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "检查医嘱"));
    panel.lastElementChild.appendChild(tagList(exams.map((item) => item.name)));
  }
  if (medications.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "用药医嘱"));
    panel.lastElementChild.appendChild(
      tagList(medications.map((item) => item.name))
    );
  }
  reports.forEach((report) => {
    panel.appendChild(el("div", "suggestion-section"));
    const section = panel.lastElementChild;
    section.appendChild(el("h3", "", `影像报告 · ${report.exam_name}`));
    section.appendChild(
      el("p", "suggestion-text", `检查所见：${report.findings}`)
    );
    section.appendChild(
      el("p", "suggestion-text", `报告结论：${report.impression}`)
    );
  });
}

async function sendCurrentMessage() {
  if (!session) return;
  const input = document.getElementById("chatInput");
  const content = input.value.trim();
  if (!content) return;
  input.value = "";
  document.getElementById("sendBtn").disabled = true;
  try {
    const next = await api("/api/patient/message", {
      method: "POST",
      body: { session_id: session.session_id, content },
    });
    render(next);
  } catch (error) {
    document.getElementById("chatLog").appendChild(
      el("div", "form-error", error.message)
    );
  } finally {
    document.getElementById("sendBtn").disabled = false;
  }
}

document.getElementById("startForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  document.getElementById("startError").textContent = "";
  const body = {
    gender: document.getElementById("genderInput").value,
    age: Number(document.getElementById("ageInput").value) || 45,
    reasoner: document.getElementById("patientModelSelect").value,
  };
  const startBtn = document.getElementById("startBtn");
  startBtn.disabled = true;
  try {
    const state = await api("/api/patient/start", { method: "POST", body });
    document.getElementById("startForm").style.display = "none";
    render(state);
  } catch (error) {
    document.getElementById("startError").textContent = error.message;
  } finally {
    startBtn.disabled = false;
  }
});

document.getElementById("sendBtn").addEventListener("click", sendCurrentMessage);
document.getElementById("chatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendCurrentMessage();
});
document.getElementById("newSessionBtn").addEventListener("click", reset);

bindDictation(
  document.getElementById("chatInput"),
  document.getElementById("dictateBtn"),
  (message) => {
    document.getElementById("startError").textContent = message;
  }
);

reset();
