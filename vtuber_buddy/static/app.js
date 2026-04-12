const state = {
  sessionId: "",
  payload: null,
  live2dReady: false,
  currentModelUrl: "",
  pixiApp: null,
  live2dModel: null,
  refreshTimer: null,
};

const elements = {
  speechBubble: document.getElementById("speechBubble"),
  providerLabel: document.getElementById("providerLabel"),
  feedButton: document.getElementById("feedButton"),
  settingsToggle: document.getElementById("settingsToggle"),
  settingsClose: document.getElementById("settingsClose"),
  settingsBackdrop: document.getElementById("settingsBackdrop"),
  settingsPanel: document.getElementById("settingsPanel"),
  settingsForm: document.getElementById("settingsForm"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  sendButton: document.getElementById("sendButton"),
  historyList: document.getElementById("historyList"),
  emotionLabel: document.getElementById("emotionLabel"),
  affectionTitle: document.getElementById("affectionTitle"),
  statusHint: document.getElementById("statusHint"),
  satietyValue: document.getElementById("satietyValue"),
  moodValue: document.getElementById("moodValue"),
  affectionValue: document.getElementById("affectionValue"),
  satietyBar: document.getElementById("satietyBar"),
  moodBar: document.getElementById("moodBar"),
  affectionBar: document.getElementById("affectionBar"),
  buddyNameInput: document.getElementById("buddyNameInput"),
  userNameInput: document.getElementById("userNameInput"),
  modelUrlInput: document.getElementById("modelUrlInput"),
  accentInput: document.getElementById("accentInput"),
  promptSuffixInput: document.getElementById("promptSuffixInput"),
  fallbackAvatar: document.getElementById("fallbackAvatar"),
  live2dStage: document.getElementById("live2dStage"),
  live2dFrame: document.getElementById("live2dFrame"),
};

function ensureSessionId() {
  const existing = window.localStorage.getItem("vtuber-buddy-session-id");
  if (existing) {
    state.sessionId = existing;
    return;
  }
  const generated =
    "browser-" +
    Math.random().toString(36).slice(2) +
    Date.now().toString(36).slice(2);
  window.localStorage.setItem("vtuber-buddy-session-id", generated);
  state.sessionId = generated;
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Session-Id": state.sessionId,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  const payload = await response.json();
  if (payload.status !== "ok") {
    throw new Error(payload.message || "Unknown API error");
  }
  return payload.data;
}

function setBusy(isBusy) {
  elements.sendButton.disabled = isBusy;
  elements.feedButton.disabled = isBusy;
  elements.chatInput.disabled = isBusy;
}

function applyAccent(color) {
  if (!color) return;
  document.documentElement.style.setProperty("--accent", color);
}

function renderHistory(history) {
  elements.historyList.innerHTML = "";
  for (const item of history.slice(-6).reverse()) {
    const row = document.createElement("div");
    row.className = "trail-item";
    row.innerHTML = `<b>${item.role === "assistant" ? "Buddy" : "你"}</b><span>${escapeHtml(item.text)}</span>`;
    elements.historyList.appendChild(row);
  }
}

function renderState(payload) {
  state.payload = payload;
  elements.speechBubble.textContent = payload.speech || "你好，我已经在这里了。";
  elements.providerLabel.textContent = payload.provider || "未连接";
  elements.emotionLabel.textContent = payload.current_emotion || "neutral";
  elements.affectionTitle.textContent = payload.stats.title;
  elements.statusHint.textContent = payload.stats.status_hint;

  updateMeter(elements.satietyValue, elements.satietyBar, payload.stats.satiety);
  updateMeter(elements.moodValue, elements.moodBar, payload.stats.mood);
  updateMeter(
    elements.affectionValue,
    elements.affectionBar,
    payload.stats.affection
  );

  elements.buddyNameInput.value = payload.settings.buddy_name || "";
  elements.userNameInput.value = payload.settings.user_name || "";
  elements.modelUrlInput.value = payload.settings.live2d_model_url || "";
  elements.accentInput.value = payload.settings.accent_color || "#ff8a65";
  elements.promptSuffixInput.value = payload.settings.system_prompt_suffix || "";

  applyAccent(payload.settings.accent_color);
  renderHistory(payload.history || []);
  updateFallbackAvatar(payload.current_emotion, payload.current_motion);
  refreshLive2D(payload.settings.live2d_model_url || "");
}

function updateMeter(label, bar, value) {
  const rounded = Math.round(value || 0);
  label.textContent = String(rounded);
  bar.style.width = `${Math.max(0, Math.min(100, rounded))}%`;
}

function updateFallbackAvatar(emotion, motion) {
  elements.fallbackAvatar.dataset.emotion = emotion || "neutral";
  elements.fallbackAvatar.dataset.motion = motion || "idle";
}

async function fetchState() {
  const payload = await requestJson("/api/state");
  renderState(payload);
}

async function sendChat(message) {
  setBusy(true);
  try {
    const payload = await requestJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    renderState(payload);
  } finally {
    setBusy(false);
  }
}

async function feedBuddy() {
  setBusy(true);
  try {
    const payload = await requestJson("/api/feed", {
      method: "POST",
      body: JSON.stringify({ food: "点心" }),
    });
    renderState(payload);
  } finally {
    setBusy(false);
  }
}

async function touchBuddy(area) {
  const payload = await requestJson("/api/touch", {
    method: "POST",
    body: JSON.stringify({ area }),
  });
  renderState(payload);
}

async function saveSettings() {
  const payload = await requestJson("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      buddy_name: elements.buddyNameInput.value.trim(),
      user_name: elements.userNameInput.value.trim(),
      live2d_model_url: elements.modelUrlInput.value.trim(),
      accent_color: elements.accentInput.value,
      system_prompt_suffix: elements.promptSuffixInput.value.trim(),
    }),
  });
  renderState(payload);
  closeSettings();
}

function openSettings() {
  elements.settingsBackdrop.classList.remove("hidden");
  elements.settingsPanel.classList.remove("hidden");
}

function closeSettings() {
  elements.settingsBackdrop.classList.add("hidden");
  elements.settingsPanel.classList.add("hidden");
}

function scheduleRefresh() {
  if (state.refreshTimer) {
    window.clearInterval(state.refreshTimer);
  }
  state.refreshTimer = window.setInterval(() => {
    fetchState().catch(() => {});
  }, 20000);
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function ensureLive2DScripts() {
  if (window.PIXI && window.PIXI.live2d) {
    return true;
  }

  const scripts = [
    "https://cdn.jsdelivr.net/npm/pixi.js@7/dist/pixi.min.js",
    "https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js",
  ];

  for (const src of scripts) {
    if (document.querySelector(`script[src="${src}"]`)) {
      continue;
    }
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  return Boolean(window.PIXI && window.PIXI.live2d);
}

async function refreshLive2D(modelUrl) {
  if (!modelUrl) {
    destroyLive2D();
    elements.live2dStage.classList.add("hidden");
    elements.fallbackAvatar.classList.remove("hidden");
    state.currentModelUrl = "";
    return;
  }

  if (state.currentModelUrl === modelUrl && state.live2dModel) {
    return;
  }

  try {
    await ensureLive2DScripts();
    destroyLive2D();

    const app = new window.PIXI.Application({
      resizeTo: elements.live2dStage,
      transparent: true,
      antialias: true,
    });
    elements.live2dStage.innerHTML = "";
    elements.live2dStage.appendChild(app.view);
    elements.live2dStage.classList.remove("hidden");
    elements.fallbackAvatar.classList.add("hidden");

    const model = await window.PIXI.live2d.Live2DModel.from(modelUrl);
    const targetScale = Math.min(
      elements.live2dStage.clientWidth / model.width,
      elements.live2dStage.clientHeight / model.height
    );
    model.scale.set(targetScale * 0.9);
    model.anchor.set(0.5, 0.5);
    model.x = elements.live2dStage.clientWidth / 2;
    model.y = elements.live2dStage.clientHeight / 2 + 30;
    model.interactive = true;
    app.stage.addChild(model);

    state.pixiApp = app;
    state.live2dModel = model;
    state.currentModelUrl = modelUrl;
  } catch (error) {
    console.warn("Live2D load failed, fallback avatar will be used.", error);
    destroyLive2D();
    elements.live2dStage.classList.add("hidden");
    elements.fallbackAvatar.classList.remove("hidden");
  }
}

function destroyLive2D() {
  if (state.live2dModel) {
    try {
      state.live2dModel.destroy();
    } catch (error) {
      console.warn(error);
    }
    state.live2dModel = null;
  }
  if (state.pixiApp) {
    try {
      state.pixiApp.destroy(true, true);
    } catch (error) {
      console.warn(error);
    }
    state.pixiApp = null;
  }
}

function registerEvents() {
  elements.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = elements.chatInput.value.trim();
    if (!message) return;
    elements.chatInput.value = "";
    await sendChat(message);
  });

  elements.feedButton.addEventListener("click", () => {
    feedBuddy().catch(console.error);
  });

  elements.settingsToggle.addEventListener("click", openSettings);
  elements.settingsClose.addEventListener("click", closeSettings);
  elements.settingsBackdrop.addEventListener("click", closeSettings);

  elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveSettings();
  });

  document.querySelectorAll(".touch-zone").forEach((button) => {
    button.addEventListener("click", () => {
      touchBuddy(button.dataset.area || "head").catch(console.error);
    });
  });
}

async function bootstrap() {
  ensureSessionId();
  registerEvents();
  scheduleRefresh();
  await fetchState();
}

bootstrap().catch((error) => {
  console.error(error);
  elements.speechBubble.textContent = "启动失败了，先检查插件日志。";
});
