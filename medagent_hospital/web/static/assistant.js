const STAGES = ["guide", "doctor", "chief"];
const ROLES = ["guide", "doctor", "chief"];
const ROLE_LABELS = {
  guide: "导医",
  nurse: "护士",
  doctor: "主诊医师",
  chief: "主任医师",
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
  document.getElementById("roleGrid").replaceChildren();
  document.getElementById("patientPanel").textContent = "尚未开始会话";
  document.getElementById("patientPanel").className = "muted empty";
  document.getElementById("orderPanel").textContent = "尚未开单";
  document.getElementById("orderPanel").className = "muted empty";
  document.querySelectorAll("#stageList li").forEach((item) => {
    item.classList.remove("active", "done");
  });
  document.getElementById("startError").textContent = "";
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "zh-CN";
  window.speechSynthesis.speak(utter);
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
      input.value = input.value ? `${input.value}，${text}` : text;
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

function render(state) {
  session = state;
  const modelSelect = document.getElementById("assistantModelSelect");
  const reasoner = state.reasoner || "rule";
  if (modelSelect.value !== reasoner) modelSelect.value = reasoner;
  renderStages(state);
  renderPatient(state);
  renderOrders(state);
  renderRoleGrid(state);
}

function renderStages(state) {
  const currentIndex = state.done ? STAGES.length : STAGES.indexOf(state.stage);
  document.querySelectorAll("#stageList li").forEach((item) => {
    const index = STAGES.indexOf(item.dataset.stage);
    item.classList.toggle("active", index === currentIndex && !state.done);
    item.classList.toggle("done", state.done || index < currentIndex);
  });
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

function renderOrders(state) {
  const panel = document.getElementById("orderPanel");
  panel.replaceChildren();
  if (
    (!state.orders || !state.orders.length) &&
    (!state.reports || !state.reports.length)
  ) {
    panel.appendChild(el("span", "muted", "尚未开单"));
    return;
  }
  const exams = state.orders.filter((item) => item.kind === "exam");
  const medications = state.orders.filter((item) => item.kind === "medication");
  if (exams.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "检查医嘱"));
    panel.lastElementChild.appendChild(
      tagList(exams.map((item) => item.name))
    );
  }
  if (medications.length) {
    panel.appendChild(el("div", "suggestion-section"));
    panel.lastElementChild.appendChild(el("h3", "", "用药医嘱"));
    panel.lastElementChild.appendChild(
      tagList(medications.map((item) => item.name))
    );
  }
  (state.reports || []).forEach((report) => {
    panel.appendChild(el("div", "suggestion-section"));
    const section = panel.lastElementChild;
    section.appendChild(el("h3", "", `影像报告 · ${report.exam_name}`));
    section.appendChild(
      el("p", "suggestion-text", `检查所见：${report.findings}`)
    );
    section.appendChild(
      el("p", "suggestion-text", `报告结论：${report.impression}`)
    );
    section.appendChild(
      el("p", "suggestion-text", `建议：${report.suggestion}`)
    );
  });
}

function roleBadge(role, state) {
  if (role === "guide") return state.department ? "分诊已确认" : "等待确认";
  if (role === "doctor") {
    if (state.done) return "已定论";
    return state.stage === "doctor" ? "主诊中" : "待分诊";
  }
  if (role === "chief") {
    if (state.done) return "已复核";
    return state.stage === "chief" ? "会诊中" : "待命";
  }
  return "";
}

function messageBubble(message, role) {
  const isAgent = message.sender !== "user";
  const bubble = el("div", isAgent ? "msg msg-agent" : "msg msg-user");
  bubble.appendChild(
    el("span", "msg-role", isAgent ? ROLE_LABELS[role] : "医生")
  );
  bubble.appendChild(document.createTextNode(message.content));
  if (message.audio_path) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = message.audio_path;
    bubble.appendChild(audio);
  }
  if (isAgent) {
    const actions = el("div", "msg-actions");
    const readBtn = el("button", "btn ghost", "朗读");
    readBtn.type = "button";
    readBtn.addEventListener("click", () => speak(message.content));
    actions.appendChild(readBtn);
    bubble.appendChild(actions);
  }
  return bubble;
}

function roleWindow(role, state) {
  const win = el("section", "role-window");
  win.dataset.role = role;
  const head = el("div", "role-head");
  head.appendChild(el("h3", "", ROLE_LABELS[role]));
  const badge = el("span", "role-badge", roleBadge(role, state));
  if (
    (role === "guide" && state.stage === "guide") ||
    (role === "doctor" && state.stage === "doctor") ||
    (role === "chief" && state.stage === "chief")
  ) {
    badge.classList.add("active-badge");
  }
  head.appendChild(badge);

  const log = el("div", "role-log");
  (state.role_messages[role] || []).forEach((message) => {
    log.appendChild(messageBubble(message, role));
  });
  log.scrollTop = log.scrollHeight;

  const inputRow = el("div", "role-input");
  const textInput = el("input", "", "");
  textInput.type = "text";
  textInput.placeholder = `与${ROLE_LABELS[role]}讨论...`;
  const sendBtn = el("button", "btn primary", "发送");
  sendBtn.type = "button";
  sendBtn.addEventListener("click", async () => {
    const content = textInput.value.trim();
    if (!content) return;
    sendBtn.disabled = true;
    try {
      const next = await api("/api/assistant/message", {
        method: "POST",
        body: { session_id: state.session_id, role, content },
      });
      render(next);
    } catch (error) {
      actions.appendChild(el("div", "form-error", error.message));
    } finally {
      sendBtn.disabled = false;
    }
  });
  textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendBtn.click();
  });
  const dictateBtn = el("button", "btn ghost", "语音转文字");
  dictateBtn.type = "button";
  dictateBtn.title = "语音转文字填入对话";
  bindDictation(textInput, dictateBtn);
  inputRow.append(textInput, sendBtn, dictateBtn);

  const actions = el("div", "role-actions");
  renderRoleActions(actions, role, state);

  win.append(head, log, inputRow, actions);
  return win;
}

function renderRoleGrid(state) {
  const grid = document.getElementById("roleGrid");
  grid.replaceChildren();
  if (state.done) {
    const banner = el("div", "done-banner");
    banner.appendChild(el("p", "", "会诊记录已保存"));
    const restart = el("button", "btn primary", "开始新会话");
    restart.type = "button";
    restart.addEventListener("click", reset);
    banner.appendChild(restart);
    grid.appendChild(banner);
  }
  ROLES.forEach((role) => grid.appendChild(roleWindow(role, state)));
}

function renderRoleActions(container, role, state) {
  container.replaceChildren();
  const row = el("div", "action-row");

  if (role === "guide") {
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
      confirm.addEventListener("click", async () => {
        confirm.disabled = true;
        try {
          const next = await api("/api/assistant/confirm", {
            method: "POST",
            body: {
              session_id: state.session_id,
              stage: "guide",
              accepted: true,
              override: select.value,
            },
          });
          render(next);
        } catch (error) {
          container.appendChild(el("div", "form-error", error.message));
        } finally {
          confirm.disabled = false;
        }
      });
      row.append(select, confirm);
    } else {
      row.appendChild(el("p", "action-note", `分诊已确认：${state.department}`));
    }
  }

  if (role === "nurse") {
    row.appendChild(
      el(
        "p",
        "action-note",
        state.department
          ? "护理通道就绪：检查与用药医嘱会在这里执行准备。"
          : "等待导医确认分诊。"
      )
    );
  }

  if (role === "doctor") {
    if (state.stage !== "doctor") {
      row.appendChild(
        el(
          "p",
          "action-note",
          state.done ? "主诊已完成。" : "等待分诊确认后进入主诊。"
        )
      );
    } else if (state.suggestion && state.suggestion.question) {
      row.appendChild(
        el("p", "action-note", `主诊追问 ${state.suggestion.question_index}/${state.suggestion.total}`)
      );
      const question = el("div", "action-question", state.suggestion.question);
      const yes = el("button", "btn primary", "有");
      const no = el("button", "btn ghost", "没有");
      const skip = el("button", "btn ghost", "跳过追问");
      [yes, no, skip].forEach((button) => {
        button.type = "button";
        button.addEventListener("click", async () => {
          setButtonsDisabled([yes, no, skip], true);
          try {
            let next;
            if (button === skip) {
              next = await api("/api/assistant/confirm", {
                method: "POST",
                body: { session_id: state.session_id, stage: "doctor", accepted: true },
              });
            } else {
              next = await api("/api/assistant/answer_question", {
                method: "POST",
                body: {
                  session_id: state.session_id,
                  symptom: state.suggestion.question,
                  present: button === yes,
                },
              });
            }
            render(next);
          } catch (error) {
            container.appendChild(el("div", "form-error", error.message));
          }
        });
      });
      row.append(question, yes, no, skip);
    } else if (state.suggestion && state.suggestion.candidates) {
      appendOrderActions(container, state, "doctor");
    }
  }

  if (role === "chief") {
    if (state.stage === "chief") {
      const history = state.suggestion.history || [];
      if (history.length) {
        const list = el("ol", "history-list");
        history.forEach((item) => list.appendChild(el("li", "", item)));
        container.appendChild(list);
      }
      appendOrderActions(container, state, "chief");
    } else {
      row.appendChild(
        el(
          "p",
          "action-note",
          state.done ? "会诊已结束。" : "主诊未请求会诊，主任处于待命状态。"
        )
      );
    }
  }

  if (row.childNodes.length) container.appendChild(row);
}

function setButtonsDisabled(buttons, disabled) {
  buttons.forEach((button) => {
    button.disabled = disabled;
  });
}

function checkList(items, checked) {
  const wrap = el("div", "check-grid");
  (items || []).forEach((name) => {
    const label = el("label", "");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = name;
    box.checked = Boolean(checked && checked.includes(name));
    label.append(box, document.createTextNode(name));
    wrap.appendChild(label);
  });
  return wrap;
}

function appendOrderActions(container, state, stage) {
  const suggestion = state.suggestion;
  const select = el("select", "", "");
  (suggestion.candidates || []).forEach((item) => {
    const option = el("option", "", `${item.disease_name} (${item.score.toFixed(2)})`);
    option.value = item.disease_id;
    if (item.disease_id === suggestion.best_id) option.selected = true;
    select.appendChild(option);
  });

  const examWrap = el("div", "suggestion-section");
  examWrap.appendChild(el("h3", "", "建议检查（可调整）"));
  const exams = checkList(suggestion.exams || []);
  examWrap.appendChild(exams);

  const medWrap = el("div", "suggestion-section");
  medWrap.appendChild(el("h3", "", "用药参考（可调整）"));
  const medications = checkList(suggestion.treatment || []);
  medWrap.appendChild(medications);

  const row = el("div", "action-row");
  row.appendChild(select);
  const confirmLabel = "结诊";
  const confirm = el("button", "btn primary", confirmLabel);
  confirm.type = "button";
  confirm.addEventListener("click", async () => {
    const body = {
      session_id: state.session_id,
      stage,
      accepted: true,
      override: select.value,
      exams: Array.from(exams.querySelectorAll(":checked")).map((box) => box.value),
      medications: Array.from(medications.querySelectorAll(":checked")).map(
        (box) => box.value
      ),
    };
    confirm.disabled = true;
    try {
      const next = await api("/api/assistant/confirm", {
        method: "POST",
        body,
      });
      render(next);
    } catch (error) {
      container.appendChild(el("div", "form-error", error.message));
    } finally {
      confirm.disabled = false;
    }
  });
  row.appendChild(confirm);

  container.append(examWrap, medWrap, row);
  if (stage === "doctor") {
    const escalate = el("button", "btn ghost", "不确定，请主任判断");
    escalate.type = "button";
    escalate.addEventListener("click", async () => {
      escalate.disabled = true;
      try {
        const next = await api("/api/assistant/confirm", {
          method: "POST",
          body: {
            session_id: state.session_id,
            stage: "doctor",
            escalate: true,
          },
        });
        render(next);
      } catch (error) {
        container.appendChild(el("div", "form-error", error.message));
      } finally {
        escalate.disabled = false;
      }
    });
    container.appendChild(escalate);
  }
}

document.getElementById("startForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  document.getElementById("startError").textContent = "";
  const body = {
    reasoner: document.getElementById("assistantModelSelect").value,
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
    document.getElementById("startForm").style.display = "none";
    render(state);
  } catch (error) {
    document.getElementById("startError").textContent = error.message;
  } finally {
    startBtn.disabled = false;
  }
});

document.getElementById("newSessionBtn").addEventListener("click", reset);

document.getElementById("assistantModelSelect").addEventListener("change", async () => {
  if (!session) return;
  const reasoner = document.getElementById("assistantModelSelect").value;
  try {
    const next = await api("/api/assistant/reasoner", {
      method: "POST",
      body: { session_id: session.session_id, reasoner },
    });
    render(next);
  } catch (error) {
    document.getElementById("startError").textContent = error.message;
  }
});

bindDictation(
  document.getElementById("symptomsInput"),
  document.getElementById("dictateBtn"),
  (message) => {
    document.getElementById("startError").textContent = message;
  }
);

reset();
