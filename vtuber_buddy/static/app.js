const state = {
  sessionId: "",
  payload: null,
  live2dConfig: null,
  currentModelKey: "",
  live2dLoadToken: 0,
  pixiApp: null,
  live2dModel: null,
  live2dInternalModel: null,
  modelUpdateHook: null,
  expressionCache: new Map(),
  activeExpressionDefinition: null,
  currentExpressionFile: "",
  refreshTimer: null,
  dragging: false,
  dragOffsetX: 0,
  dragOffsetY: 0,
  lastPointerX: NaN,
  lastPointerY: NaN,
  currentMouthValue: 0,
  speakingUntil: 0,
  speechFrame: 0,
  canvasHandlersBound: false,
};

const elements = {
  speechBubble: document.getElementById("speechBubble"),
  providerLabel: document.getElementById("providerLabel"),
  live2dStatus: document.getElementById("live2dStatus"),
  modelRuntimeLabel: document.getElementById("modelRuntimeLabel"),
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
  modelSelect: document.getElementById("modelSelect"),
  modelUrlInput: document.getElementById("modelUrlInput"),
  mouseFollowInput: document.getElementById("mouseFollowInput"),
  resetViewButton: document.getElementById("resetViewButton"),
  clearCustomModelButton: document.getElementById("clearCustomModelButton"),
  accentInput: document.getElementById("accentInput"),
  promptSuffixInput: document.getElementById("promptSuffixInput"),
  fallbackAvatar: document.getElementById("fallbackAvatar"),
  live2dStage: document.getElementById("live2dStage"),
  live2dCanvas: document.getElementById("live2dCanvas"),
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
  if (!color) {
    return;
  }
  document.documentElement.style.setProperty("--accent", color);
}

function updateMeter(label, bar, value) {
  const rounded = Math.round(value || 0);
  label.textContent = String(rounded);
  bar.style.width = `${Math.max(0, Math.min(100, rounded))}%`;
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderHistory(history) {
  elements.historyList.innerHTML = "";
  for (const item of (history || []).slice(-6).reverse()) {
    const row = document.createElement("div");
    row.className = "trail-item";
    row.innerHTML = `<b>${item.role === "assistant" ? "Buddy" : "你"}</b><span>${escapeHtml(item.text)}</span>`;
    elements.historyList.appendChild(row);
  }
}

function renderModelOptions(live2dConfig, selectedKey) {
  const models = Array.isArray(live2dConfig?.models) ? live2dConfig.models : [];
  elements.modelSelect.innerHTML = "";

  if (models.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "未发现本地 Live2D 模型";
    elements.modelSelect.appendChild(option);
    elements.modelSelect.disabled = true;
    return;
  }

  for (const model of models) {
    const option = document.createElement("option");
    option.value = model.selection_key;
    option.textContent = `${model.directory_name || model.model_name} (${model.source === "builtin" ? "内置" : "工作区"})`;
    elements.modelSelect.appendChild(option);
  }

  elements.modelSelect.disabled = false;
  elements.modelSelect.value = selectedKey || models[0].selection_key;
}

function describeLive2D(config) {
  if (!config || !config.available) {
    return {
      badge: "Live2D 未发现",
      runtime: "回退到占位立绘",
    };
  }
  if (config.is_custom_model) {
    return {
      badge: "Live2D 外链",
      runtime: "当前使用外部模型 URL",
    };
  }
  return {
    badge: `Live2D ${config.source === "builtin" ? "内置" : "工作区"}`,
    runtime: `${config.directory_name || config.model_name} 已激活`,
  };
}

function updateFallbackAvatar(emotion, motion) {
  elements.fallbackAvatar.dataset.emotion = emotion || "neutral";
  elements.fallbackAvatar.dataset.motion = motion || "idle";
}

async function renderState(payload) {
  const previousPayload = state.payload;
  const speechChanged = (previousPayload?.speech || "") !== (payload.speech || "");
  const emotionChanged =
    (previousPayload?.current_emotion || "") !== (payload.current_emotion || "");
  const motionChanged =
    (previousPayload?.current_motion || "") !== (payload.current_motion || "");

  state.payload = payload;
  state.live2dConfig = payload.live2d || null;

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
  elements.mouseFollowInput.checked = Boolean(
    payload.settings.live2d_mouse_follow_enabled
  );
  elements.accentInput.value = payload.settings.accent_color || "#ff8a65";
  elements.promptSuffixInput.value = payload.settings.system_prompt_suffix || "";

  renderModelOptions(payload.live2d, payload.settings.live2d_selection_key);
  renderHistory(payload.history || []);
  applyAccent(payload.settings.accent_color);
  updateFallbackAvatar(payload.current_emotion, payload.current_motion);

  const live2dDescription = describeLive2D(payload.live2d);
  elements.live2dStatus.textContent = live2dDescription.badge;
  elements.modelRuntimeLabel.textContent = live2dDescription.runtime;

  if (speechChanged) {
    triggerSpeechAnimation(payload.speech || "");
  }

  await syncLive2D(payload.live2d, {
    emotion: payload.current_emotion,
    motion: payload.current_motion,
    emotionChanged,
    motionChanged,
  });
}

async function fetchState() {
  const payload = await requestJson("/api/state");
  await renderState(payload);
}

async function sendChat(message) {
  setBusy(true);
  try {
    const payload = await requestJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    await renderState(payload);
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
    await renderState(payload);
  } finally {
    setBusy(false);
  }
}

async function touchBuddy(area) {
  const payload = await requestJson("/api/touch", {
    method: "POST",
    body: JSON.stringify({ area }),
  });
  await renderState(payload);
}

async function saveSettings() {
  const payload = await requestJson("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      buddy_name: elements.buddyNameInput.value.trim(),
      user_name: elements.userNameInput.value.trim(),
      live2d_selection_key: elements.modelSelect.value,
      live2d_model_url: elements.modelUrlInput.value.trim(),
      live2d_mouse_follow_enabled: elements.mouseFollowInput.checked,
      accent_color: elements.accentInput.value,
      system_prompt_suffix: elements.promptSuffixInput.value.trim(),
    }),
  });
  await renderState(payload);
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

function assertLive2DRuntimeReady() {
  if (!window.PIXI) {
    throw new Error("PIXI 未加载");
  }
  if (!window.Live2DCubismCore) {
    throw new Error("live2dcubismcore 未加载");
  }
  if (!window.PIXI.live2d || !window.PIXI.live2d.Live2DModel) {
    throw new Error("pixi-live2d-display 未加载");
  }
}

function ensurePixiApp() {
  const stageWidth = elements.live2dStage.clientWidth;
  const stageHeight = elements.live2dStage.clientHeight;

  if (state.pixiApp) {
    if (
      state.pixiApp.renderer &&
      stageWidth > 0 &&
      stageHeight > 0 &&
      typeof state.pixiApp.renderer.resize === "function"
    ) {
      state.pixiApp.renderer.resize(stageWidth, stageHeight);
      state.pixiApp.stage.hitArea = state.pixiApp.screen;
    }
    return state.pixiApp;
  }

  assertLive2DRuntimeReady();

  const app = new window.PIXI.Application({
    view: elements.live2dCanvas,
    resizeTo: elements.live2dStage,
    autoStart: true,
    antialias: true,
    backgroundAlpha: 0,
  });

  if (app.stage) {
    app.stage.interactive = true;
    app.stage.hitArea = app.screen;
  }

  if (
    app.renderer &&
    stageWidth > 0 &&
    stageHeight > 0 &&
    typeof app.renderer.resize === "function"
  ) {
    app.renderer.resize(stageWidth, stageHeight);
  }

  state.pixiApp = app;
  bindCanvasHandlers();
  return app;
}

async function waitForStageLayout() {
  for (let index = 0; index < 6; index += 1) {
    if (
      elements.live2dStage.clientWidth > 0 &&
      elements.live2dStage.clientHeight > 0
    ) {
      return;
    }
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
  }
}

function bindCanvasHandlers() {
  if (state.canvasHandlersBound || !state.pixiApp) {
    return;
  }

  const canvas = state.pixiApp.view;

  canvas.addEventListener("pointerdown", (event) => {
    if (!state.live2dModel) {
      return;
    }
    state.dragging = true;
    state.dragOffsetX = state.live2dModel.x - event.offsetX;
    state.dragOffsetY = state.live2dModel.y - event.offsetY;
    canvas.setPointerCapture?.(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    state.lastPointerX = event.offsetX;
    state.lastPointerY = event.offsetY;

    if (state.dragging && state.live2dModel) {
      state.live2dModel.x = event.offsetX + state.dragOffsetX;
      state.live2dModel.y = event.offsetY + state.dragOffsetY;
      persistLive2DTransform();
    }

    updateLive2DFocus();
  });

  const stopDrag = () => {
    state.dragging = false;
  };

  canvas.addEventListener("pointerup", stopDrag);
  canvas.addEventListener("pointerleave", stopDrag);
  canvas.addEventListener("pointercancel", stopDrag);

  canvas.addEventListener(
    "wheel",
    (event) => {
      if (!state.live2dModel) {
        return;
      }
      event.preventDefault();
      const nextScale = clamp(
        state.live2dModel.scale.x * (event.deltaY < 0 ? 1.06 : 0.94),
        0.08,
        3.2
      );
      state.live2dModel.scale.set(nextScale);
      persistLive2DTransform();
      updateLive2DFocus();
    },
    { passive: false }
  );

  state.canvasHandlersBound = true;
}

async function syncLive2D(config, changeSet) {
  if (!config || !config.available || !config.model_url) {
    hideLive2DStage();
    destroyLive2DModel();
    state.currentModelKey = "";
    return;
  }

  const modelKey = `${config.selection_key}|${config.model_url}`;
  const modelChanged = modelKey !== state.currentModelKey || !state.live2dModel;

  if (modelChanged) {
    await loadLive2DModel(config);
  }

  if (!state.live2dModel) {
    return;
  }

  applyMouseFollow(config.mouse_follow_enabled);

  if (modelChanged || changeSet.emotionChanged) {
    await applyEmotionExpression(config, changeSet.emotion);
  }

  if (modelChanged || changeSet.motionChanged) {
    await playMappedMotion(config, changeSet.motion);
  }
}

async function loadLive2DModel(config) {
  const loadToken = ++state.live2dLoadToken;
  state.currentModelKey = `${config.selection_key}|${config.model_url}`;
  state.currentExpressionFile = "";
  state.activeExpressionDefinition = null;

  try {
    destroyLive2DModel();
    elements.live2dStage.classList.remove("hidden");
    elements.fallbackAvatar.classList.add("hidden");
    await waitForStageLayout();

    const app = ensurePixiApp();
    const model = await window.PIXI.live2d.Live2DModel.from(config.model_url, {
      autoInteract: false,
    });

    if (loadToken !== state.live2dLoadToken) {
      try {
        model.destroy();
      } catch (error) {
        console.warn(error);
      }
      return;
    }

    app.stage.removeChildren();
    app.stage.addChild(model);
    model.anchor.set(0.5, 0.5);
    model.interactive = true;
    model.autoInteract = false;
    if (typeof model.unregisterInteraction === "function") {
      model.unregisterInteraction();
    }

    state.live2dModel = model;
    attachModelUpdateHook(config);
    restoreOrApplyDefaultTransform();
    updateLive2DFocus(true);

    const stageWidth = Math.round(elements.live2dStage.clientWidth || 0);
    const stageHeight = Math.round(elements.live2dStage.clientHeight || 0);
    elements.modelRuntimeLabel.textContent = `${config.directory_name || config.model_name} 已激活 ${stageWidth}x${stageHeight}`;
  } catch (error) {
    console.warn("Live2D load failed, fallback avatar will be used.", error);
    state.live2dModel = null;
    elements.live2dStatus.textContent = "Live2D 加载失败";
    elements.modelRuntimeLabel.textContent =
      error?.message || "已回退到占位立绘";
    hideLive2DStage();
  }
}

function hideLive2DStage() {
  elements.live2dStage.classList.add("hidden");
  elements.fallbackAvatar.classList.remove("hidden");
}

function destroyLive2DModel() {
  detachModelUpdateHook();
  state.currentExpressionFile = "";
  state.activeExpressionDefinition = null;

  if (state.live2dModel) {
    try {
      state.live2dModel.destroy({ children: true });
    } catch (error) {
      console.warn(error);
    }
  }

  state.live2dModel = null;
  if (state.pixiApp?.stage) {
    state.pixiApp.stage.removeChildren();
  }
}

function attachModelUpdateHook(config) {
  detachModelUpdateHook();

  const internalModel = state.live2dModel?.internalModel;
  if (!internalModel || typeof internalModel.on !== "function") {
    return;
  }

  state.live2dInternalModel = internalModel;
  state.modelUpdateHook = () => {
    applyMouthValue(config, state.currentMouthValue);
    applyExpressionDefinition(state.activeExpressionDefinition);
  };
  internalModel.on("beforeModelUpdate", state.modelUpdateHook);
}

function detachModelUpdateHook() {
  if (
    state.live2dInternalModel &&
    state.modelUpdateHook &&
    typeof state.live2dInternalModel.off === "function"
  ) {
    state.live2dInternalModel.off("beforeModelUpdate", state.modelUpdateHook);
  }

  state.live2dInternalModel = null;
  state.modelUpdateHook = null;
}

async function applyEmotionExpression(config, emotion) {
  const mapping = config?.emotion_expression_map || {};
  const targetFile = mapping[emotion] || mapping.neutral || "";

  if (!targetFile) {
    state.activeExpressionDefinition = null;
    state.currentExpressionFile = "";
    return;
  }

  if (targetFile === state.currentExpressionFile && state.activeExpressionDefinition) {
    return;
  }

  const expressionItem = (config.expressions || []).find(
    (item) => item.file === targetFile
  );
  if (!expressionItem) {
    state.activeExpressionDefinition = null;
    state.currentExpressionFile = "";
    return;
  }

  const definition = await loadExpressionDefinition(expressionItem);
  state.activeExpressionDefinition = definition;
  state.currentExpressionFile = targetFile;
}

async function loadExpressionDefinition(expressionItem) {
  if (state.expressionCache.has(expressionItem.url)) {
    return state.expressionCache.get(expressionItem.url);
  }

  const response = await fetch(expressionItem.url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`加载表情失败：${expressionItem.name}`);
  }

  const payload = await response.json();
  const definition = {
    name: expressionItem.name,
    file: expressionItem.file,
    parameters: Array.isArray(payload?.Parameters)
      ? payload.Parameters.filter((item) => item && typeof item === "object")
          .map((item) => ({
            id: String(item.Id || ""),
            value: typeof item.Value === "number" ? item.Value : 0,
            blend: normalizeExpressionBlend(item.Blend),
          }))
          .filter((item) => item.id)
      : [],
  };

  state.expressionCache.set(expressionItem.url, definition);
  return definition;
}

function normalizeExpressionBlend(blend) {
  const normalized = String(blend || "").trim().toLowerCase();
  if (normalized === "add") {
    return "Add";
  }
  if (normalized === "multiply") {
    return "Multiply";
  }
  return "Set";
}

function applyExpressionDefinition(definition) {
  const coreModel = state.live2dModel?.internalModel?.coreModel;
  if (!coreModel || !definition?.parameters?.length) {
    return;
  }

  for (const parameter of definition.parameters) {
    try {
      if (
        parameter.blend === "Add" &&
        typeof coreModel.addParameterValueById === "function"
      ) {
        coreModel.addParameterValueById(parameter.id, parameter.value);
        continue;
      }
      if (
        parameter.blend === "Multiply" &&
        typeof coreModel.multiplyParameterValueById === "function"
      ) {
        coreModel.multiplyParameterValueById(parameter.id, parameter.value);
        continue;
      }
      coreModel.setParameterValueById(parameter.id, parameter.value);
    } catch (error) {
      console.warn(`Failed to apply expression ${parameter.id}`, error);
    }
  }
}

function applyMouthValue(config, value) {
  const coreModel = state.live2dModel?.internalModel?.coreModel;
  if (!coreModel || typeof coreModel.setParameterValueById !== "function") {
    return;
  }

  const lipSyncIds = Array.isArray(config?.lip_sync_parameter_ids)
    ? config.lip_sync_parameter_ids
    : [];

  for (const parameterId of lipSyncIds) {
    try {
      coreModel.setParameterValueById(parameterId, value);
    } catch (error) {
      console.warn(`Failed to update mouth parameter ${parameterId}`, error);
    }
  }

  if (config?.mouth_form_parameter_id) {
    try {
      coreModel.setParameterValueById(config.mouth_form_parameter_id, 0);
    } catch (error) {
      console.warn("Failed to reset mouth form parameter", error);
    }
  }
}

async function playMappedMotion(config, motionAlias) {
  const mapping = config?.motion_alias_map || {};
  const motion = mapping[motionAlias] || mapping.idle;

  if (!motion || !state.live2dModel || typeof state.live2dModel.motion !== "function") {
    return;
  }

  try {
    await state.live2dModel.motion(motion.group, motion.index);
  } catch (error) {
    console.warn("Failed to play motion", error);
  }
}

function triggerSpeechAnimation(text) {
  const duration = Math.min(2800, 700 + String(text || "").length * 35);
  state.speakingUntil = Date.now() + duration;
  if (!state.speechFrame) {
    tickSpeechAnimation();
  }
}

function tickSpeechAnimation() {
  const now = Date.now();
  if (now >= state.speakingUntil) {
    state.currentMouthValue = 0;
    state.speechFrame = 0;
    return;
  }

  const remaining = state.speakingUntil - now;
  const intensity = Math.min(1, remaining / 400);
  state.currentMouthValue = Math.max(
    0,
    0.1 + Math.abs(Math.sin(now / 75)) * 0.82 * intensity
  );
  state.speechFrame = window.requestAnimationFrame(tickSpeechAnimation);
}

function applyMouseFollow(enabled) {
  if (!state.live2dModel) {
    return;
  }
  if (!enabled) {
    resetLive2DFocus();
    return;
  }
  updateLive2DFocus(true);
}

function updateLive2DFocus(force = false) {
  if (!state.live2dConfig?.mouse_follow_enabled && !force) {
    return;
  }

  const model = state.live2dModel;
  const focusController = model?.internalModel?.focusController;
  if (!model || !focusController || typeof focusController.focus !== "function") {
    return;
  }

  if (!Number.isFinite(state.lastPointerX) || !Number.isFinite(state.lastPointerY)) {
    if (force) {
      focusController.focus(0, 0, true);
    }
    return;
  }

  const point = toModelPoint(model, state.lastPointerX, state.lastPointerY);
  if (!point) {
    return;
  }

  const width = model.internalModel?.originalWidth || model.width || 1;
  const height = model.internalModel?.originalHeight || model.height || 1;
  const rawX = clamp((point.x / width) * 2 - 1, -1, 1);
  const rawY = clamp((point.y / height) * 2 - 1, -1, 1);
  const distance = Math.hypot(rawX, rawY);

  if (distance <= 0.0001) {
    focusController.focus(0, 0);
    return;
  }

  focusController.focus(rawX / distance, -rawY / distance);
}

function resetLive2DFocus() {
  const focusController = state.live2dModel?.internalModel?.focusController;
  if (!focusController || typeof focusController.focus !== "function") {
    return;
  }
  focusController.focus(0, 0, true);
}

function toModelPoint(model, x, y) {
  if (!window.PIXI || typeof window.PIXI.Point !== "function") {
    return null;
  }
  if (typeof model.toModelPosition !== "function") {
    return null;
  }
  return model.toModelPosition(
    new window.PIXI.Point(x, y),
    new window.PIXI.Point()
  );
}

function restoreOrApplyDefaultTransform() {
  const transform = loadSavedTransform();
  if (transform && state.live2dModel && isTransformVisible(transform)) {
    state.live2dModel.x = transform.x;
    state.live2dModel.y = transform.y;
    state.live2dModel.scale.set(transform.scale);
    return;
  }
  applyDefaultTransform();
  persistLive2DTransform();
}

function applyDefaultTransform() {
  if (!state.live2dModel || !state.pixiApp) {
    return;
  }

  const bounds = measureModelBaseSize(state.live2dModel);
  const stageWidth = Math.max(
    state.pixiApp.screen.width || 0,
    elements.live2dStage.clientWidth || 0,
    1
  );
  const stageHeight = Math.max(
    state.pixiApp.screen.height || 0,
    elements.live2dStage.clientHeight || 0,
    1
  );
  const widthRatio = stageWidth / Math.max(bounds.width, 1);
  const heightRatio = stageHeight / Math.max(bounds.height, 1);
  const scale = clamp(Math.min(widthRatio, heightRatio) * 0.82, 0.08, 3.2);

  state.live2dModel.scale.set(scale);
  state.live2dModel.x = stageWidth * 0.5;
  state.live2dModel.y = stageHeight * 0.62;
}

function measureModelBaseSize(model) {
  const originalWidth = model.internalModel?.originalWidth;
  const originalHeight = model.internalModel?.originalHeight;

  if (
    Number.isFinite(originalWidth) &&
    originalWidth > 0 &&
    Number.isFinite(originalHeight) &&
    originalHeight > 0
  ) {
    return {
      width: originalWidth,
      height: originalHeight,
    };
  }

  if (typeof model.getLocalBounds === "function") {
    const bounds = model.getLocalBounds();
    if (bounds?.width > 0 && bounds?.height > 0) {
      return { width: bounds.width, height: bounds.height };
    }
  }

  const scaleX = Math.max(Math.abs(model.scale.x) || 0, 0.0001);
  const scaleY = Math.max(Math.abs(model.scale.y) || 0, 0.0001);
  return {
    width: model.width / scaleX,
    height: model.height / scaleY,
  };
}

function persistLive2DTransform() {
  if (!state.live2dModel || !state.live2dConfig) {
    return;
  }

  window.localStorage.setItem(
    transformStorageKey(),
    JSON.stringify({
      x: roundTo(state.live2dModel.x, 2),
      y: roundTo(state.live2dModel.y, 2),
      scale: roundTo(state.live2dModel.scale.x, 4),
    })
  );
}

function loadSavedTransform() {
  const text = window.localStorage.getItem(transformStorageKey());
  if (!text) {
    return null;
  }

  try {
    const payload = JSON.parse(text);
    if (
      typeof payload.x === "number" &&
      typeof payload.y === "number" &&
      typeof payload.scale === "number" &&
      Number.isFinite(payload.x) &&
      Number.isFinite(payload.y) &&
      Number.isFinite(payload.scale) &&
      payload.scale >= 0.08 &&
      payload.scale <= 3.2
    ) {
      return payload;
    }
  } catch (error) {
    console.warn(error);
  }

  return null;
}

function isTransformVisible(transform) {
  const stageWidth = Math.max(elements.live2dStage.clientWidth || 0, 1);
  const stageHeight = Math.max(elements.live2dStage.clientHeight || 0, 1);
  return (
    transform.x >= -stageWidth * 0.5 &&
    transform.x <= stageWidth * 1.5 &&
    transform.y >= -stageHeight * 0.5 &&
    transform.y <= stageHeight * 1.7
  );
}

function resetLive2DView() {
  if (!state.live2dModel) {
    return;
  }
  window.localStorage.removeItem(transformStorageKey());
  applyDefaultTransform();
  persistLive2DTransform();
}

function transformStorageKey() {
  const config = state.live2dConfig;
  return `vtuber-buddy-live2d:${config?.selection_key || config?.model_url || "default"}`;
}

function roundTo(value, digits) {
  const base = 10 ** digits;
  return Math.round((value || 0) * base) / base;
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function registerEvents() {
  elements.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = elements.chatInput.value.trim();
    if (!message) {
      return;
    }
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

  elements.resetViewButton.addEventListener("click", () => {
    resetLive2DView();
  });

  elements.clearCustomModelButton.addEventListener("click", () => {
    elements.modelUrlInput.value = "";
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
  elements.speechBubble.textContent = "启动失败了，先检查一下插件日志。";
});
