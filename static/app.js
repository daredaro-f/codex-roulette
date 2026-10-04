const $ = (id) => document.getElementById(id);
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const CONNECTION_STORAGE_KEY = "codex-roulette.connection.v1";
const state = {
  features: [], selectedIds: new Set(), result: null, mode: "demo", busy: false,
  controller: null, requestId: 0, count: 0, models: [], modelsBusy: false,
  timeoutSeconds: 30, demoOnly: false, elapsedTimer: null, audio: null, audioNodes: new Set(), audioVersion: 0,
  connectionBase: "", preferredModel: "", reconnectOnLoad: false,
};
const cards = [$("feature-card"), $("topic-card"), $("constraint-card")];
let popoverTrigger = null;
let popoverFeature = null;
let popoverPinned = false;
let popoverCloseTimer = null;
let suppressPopoverFocus = false;
let copyResetTimer = null;

function localBaseUrl(value) {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
        url.username || url.password || url.search || url.hash || !["/", "/v1", "/v1/"].includes(url.pathname)) return null;
    return `${url.origin}/v1`;
  } catch { return null; }
}

function readConnectionPreferences() {
  let raw;
  try { raw = localStorage.getItem(CONNECTION_STORAGE_KEY); } catch {
    $("connection-save-note").textContent = "このブラウザでは設定を保存できない。接続確認はそのまま使えるよ。";
    return null;
  }
  try {
    const saved = JSON.parse(raw);
    if (!saved || saved.version !== 1 || typeof saved.baseUrl !== "string" || !localBaseUrl(saved.baseUrl)) return null;
    return {
      baseUrl: localBaseUrl(saved.baseUrl),
      modelId: typeof saved.modelId === "string" && saved.modelId.length <= 250 ? saved.modelId : "",
      mode: saved.mode === "local" ? "local" : "demo",
      reconnect: saved.reconnect === true,
    };
  } catch { return null; }
}

function saveConnectionPreferences() {
  if (state.demoOnly || !state.connectionBase) return;
  try {
    localStorage.setItem(CONNECTION_STORAGE_KEY, JSON.stringify({
      version: 1, baseUrl: state.connectionBase, modelId: state.preferredModel,
      mode: state.mode, reconnect: state.reconnectOnLoad,
    }));
    $("connection-save-note").textContent = "このブラウザに保存済み。更新後も設定を戻すよ。";
  } catch {
    $("connection-save-note").textContent = "このブラウザでは設定を保存できない。接続確認はそのまま使えるよ。";
  }
}

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function readable(value) {
  return Array.isArray(value) ? value.join("\n") : String(value ?? "");
}

function quietMotion() {
  return $("motion-toggle").checked || motionPreference.matches;
}

function updateMotion() {
  document.documentElement.dataset.motion = quietMotion() ? "quiet" : "full";
  if (quietMotion()) $("confetti").replaceChildren();
}

function setStatus(message, kind = "ready") {
  $("generation-status").textContent = message;
  $("status-dot").dataset.state = kind;
}

function clearError() {
  $("error-panel").hidden = true;
}

function showError(error) {
  $("error-message").textContent = error.message || "実験を引けなかった。";
  $("error-hint").textContent = error.hint || "もう一度試すか、デモで操作感を確かめよう。";
  $("error-panel").hidden = false;
  $("demo-fallback").hidden = state.mode === "demo";
  setStatus("実験を引けなかった。下の案内を確認してね。", "error");
}

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw Object.assign(new Error("アプリとの接続が切れた。"), { hint: "Pythonのサーバーが動いているか確認して、もう一度試そう。" });
  }
  let body;
  try { body = await response.json(); } catch {
    throw Object.assign(new Error("アプリからの返事を読み取れなかった。"), { hint: "Pythonのサーバーを確認して、ページを読み込み直そう。" });
  }
  if (!response.ok) {
    const detail = body.detail;
    if (detail && !Array.isArray(detail) && typeof detail === "object") {
      throw Object.assign(new Error(detail.message || "処理を完了できなかった。"), { code: detail.code, hint: detail.hint });
    }
    throw Object.assign(new Error(Array.isArray(detail) ? "入力した設定を確認してね。" : String(detail || "処理を完了できなかった。")), { hint: "機能の選択、モデル、接続先のURLを確認して、もう一度試そう。" });
  }
  return body;
}

function updateControls() {
  const selectedCount = state.selectedIds.size;
  const missingModel = state.mode === "local" && !$("model-select").value;
  $("draw-button").disabled = state.busy || state.modelsBusy || !selectedCount || missingModel;
  $("draw-label").textContent = state.busy ? "実験を考え中…" : state.count ? "もう一度引く！" : "実験を引く！";
  $("cancel-button").hidden = !state.busy;
  $("feature-count").textContent = `${selectedCount} / ${state.features.length} ON`;
  $("feature-selection-note").textContent = selectedCount ? `${selectedCount}個の機能から選ぶよ。説明ボタンにカーソルを合わせると詳しく読める。` : "機能を1つ以上ONにしてから、実験を引こう。";
  $("draw-hint").textContent = !selectedCount ? "「使える新機能を選ぶ」で、機能を1つ以上ONにしてね。" : missingModel ? "「LM Studio 接続設定」で接続確認して、モデルを選ぼう。" : state.mode === "demo" ? "デモは準備済みのお題から抽選。ローカルLLMへ切り替えると、新しいお題を生成する。" : "このPCのローカルLLMが、選んだ新機能で遊べる実験を考える。";
  $("connect-button").disabled = state.busy || state.modelsBusy || state.demoOnly;
  $("base-url-input").disabled = state.busy || state.modelsBusy || state.demoOnly;
  $("model-select").disabled = state.busy || state.modelsBusy || state.models.length === 0 || state.demoOnly;
  $("minutes-select").disabled = state.busy;
  $("chaos-select").disabled = state.busy;
  document.querySelectorAll('input[name="generation-mode"]').forEach((input) => { input.disabled = state.busy || (input.value === "local" && state.demoOnly); });
  document.querySelectorAll(".feature-option input").forEach((input) => { input.disabled = state.busy; });
}

function setBusy(busy) {
  state.busy = busy;
  $("reels").setAttribute("aria-busy", String(busy));
  if (!busy && state.elapsedTimer) {
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
  }
  updateControls();
}

function featureById(id) {
  return state.features.find((feature) => feature.id === id);
}

function renderFeatureOptions() {
  $("feature-options").replaceChildren();
  for (const feature of state.features) {
    const row = textElement("div", "", "feature-option");
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = feature.id;
    checkbox.checked = state.selectedIds.has(feature.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedIds.add(feature.id); else state.selectedIds.delete(feature.id);
      updateControls();
    });
    const description = document.createElement("span");
    description.append(textElement("span", feature.name, "feature-option-name"));
    description.append(textElement("span", feature.default_enabled ? "利用可否を確認して選ぼう" : "事前準備が必要なコース", "feature-option-note"));
    label.append(checkbox, description);
    const help = textElement("button", "説明", "feature-help");
    help.type = "button";
    help.setAttribute("aria-label", `${feature.name}の説明を開く`);
    help.setAttribute("aria-controls", "feature-popover");
    help.setAttribute("aria-expanded", "false");
    bindPopover(help, () => feature);
    row.append(label, help);
    $("feature-options").append(row);
  }
}

function renderResult(result) {
  $("feature-title").textContent = result.feature.short_name || result.feature.name;
  $("feature-subtitle").textContent = "カーソルを合わせて、新機能を知ろう";
  $("topic-title").textContent = result.topic;
  $("constraint-title").textContent = result.constraint;
  $("feature-info").disabled = false;
}

function resetCards() {
  cards.forEach((card) => card.classList.remove("is-revealing", "is-settled"));
  if (state.result) renderResult(state.result);
  else {
    $("feature-title").replaceChildren(textElement("span", "新機能を、"), document.createElement("br"), textElement("span", "ひとつ。"));
    $("topic-title").replaceChildren(textElement("span", "ひらめきを、"), document.createElement("br"), textElement("span", "かたちに。"));
    $("constraint-title").replaceChildren(textElement("span", "常識を、"), document.createElement("br"), textElement("span", "ひとつ外す。"));
    $("feature-subtitle").textContent = "新しい道具から実験をはじめる";
    $("feature-info").disabled = true;
  }
}

function cancelGeneration() {
  state.requestId += 1;
  state.controller?.abort();
  state.controller = null;
  resetCards();
  setBusy(false);
  setStatus("待機をやめた。もう一度引けるよ。");
}

function soundStatus(message, audioState) {
  $("sound-status").textContent = message;
  $("sound-status").dataset.audioState = audioState;
  $("sound-status").hidden = !message;
}

function stopTones() {
  for (const oscillator of state.audioNodes) {
    try { oscillator.stop(); } catch { /* 終了済みの音はそのまま。 */ }
  }
  state.audioNodes.clear();
}

async function playTone(kind) {
  if (!$("sound-toggle").checked) return;
  const audioVersion = state.audioVersion;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) {
    soundStatus("このブラウザでは音を再生できない。通常のブラウザでも試せるよ。", "unsupported");
    return;
  }
  let resumeTimer;
  try {
    if (!state.audio || state.audio.state === "closed") state.audio = new AudioContext();
    const context = state.audio;
    // スイッチ/抽選の操作中に開始し、再開できてから音を予約する。
    if (context.state !== "running") {
      soundStatus("音を準備している…", "starting");
      await Promise.race([
        context.resume(),
        new Promise((_, reject) => { resumeTimer = setTimeout(() => reject(new Error("audio resume timeout")), 2000); }),
      ]);
    }
    if (!$("sound-toggle").checked || audioVersion !== state.audioVersion) return;
    if (context.state !== "running") throw new Error("audio context is not running");
    const now = context.currentTime + .02;
    const frequencies = kind === "complete" ? [440, 660, 880] : kind === "enable" ? [660, 880] : [520];
    frequencies.forEach((frequency, index) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0, now + index * .09);
      gain.gain.linearRampToValueAtTime(.14, now + index * .09 + .012);
      gain.gain.exponentialRampToValueAtTime(.0001, now + index * .09 + .19);
      oscillator.connect(gain);
      gain.connect(context.destination);
      state.audioNodes.add(oscillator);
      oscillator.onended = () => {
        state.audioNodes.delete(oscillator);
        oscillator.disconnect();
        gain.disconnect();
      };
      oscillator.start(now + index * .09);
      oscillator.stop(now + index * .09 + .2);
    });
    soundStatus("音ON。抽選の開始と確定で短い音が鳴るよ。", "running");
  } catch (error) {
    if ($("sound-toggle").checked && audioVersion === state.audioVersion) {
      soundStatus("音を再生できなかった。音のスイッチを入れ直してみてね。", "blocked");
      console.warn("効果音を再生できなかった:", error.name);
    }
  } finally {
    clearTimeout(resumeTimer);
  }
}

function confetti() {
  if (quietMotion()) return;
  const container = $("confetti");
  container.replaceChildren();
  for (let i = 0; i < 28; i += 1) {
    const piece = textElement("span", "", "confetti-piece");
    piece.style.setProperty("--left", `${4 + Math.random() * 92}%`);
    piece.style.setProperty("--color", ["var(--accent-cyan)", "var(--accent-magenta)", "var(--accent-lime)"][i % 3]);
    piece.style.setProperty("--delay", `${Math.random() * 150}ms`);
    piece.style.setProperty("--drift", `${Math.random() * 100 - 50}px`);
    piece.style.setProperty("--spin", `${Math.random() * 500 - 250}deg`);
    container.append(piece);
  }
  setTimeout(() => container.replaceChildren(), 1500);
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function revealResult(result, requestId) {
  if (quietMotion()) { renderResult(result); return state.requestId === requestId; }
  cards.forEach((card) => { card.classList.remove("is-settled"); card.classList.add("is-revealing"); });
  renderResult(result);
  await delay(180);
  for (const card of cards) {
    if (state.requestId !== requestId) return false;
    card.classList.remove("is-revealing");
    card.classList.add("is-settled");
    await delay(260);
  }
  await delay(180);
  return state.requestId === requestId;
}

async function generateExperiment() {
  if ($("draw-button").disabled) return;
  clearError();
  closePopover();
  playTone("click");
  const requestId = ++state.requestId;
  const selectedIds = [...state.selectedIds];
  state.controller = new AbortController();
  setBusy(true);
  const startedAt = Date.now();
  const waitingText = state.mode === "local" ? "ローカルLLMが実験を考え中…" : "デモのお題を選んでいる…";
  setStatus(waitingText, "busy");
  state.elapsedTimer = setInterval(() => {
    if (state.requestId === requestId) setStatus(`${waitingText} ${Math.floor((Date.now() - startedAt) / 1000)}秒`, "busy");
  }, 1000);
  try {
    const result = await apiRequest("/api/generate", {
      method: "POST", signal: state.controller.signal,
      body: JSON.stringify({ feature_ids: selectedIds, mode: state.mode, model: $("model-select").value, reasoning_off: state.models.find((model) => model.id === $("model-select").value)?.reasoning_off_available === true, base_url: $("base-url-input").value.trim(), minutes: Number($("minutes-select").value), chaos: Number($("chaos-select").value) }),
    });
    if (state.requestId !== requestId) return;
    if (!selectedIds.includes(result.feature_id) || !result.feature || typeof result.topic !== "string" || typeof result.constraint !== "string" || typeof result.application !== "string" || typeof result.prompt !== "string") {
      throw Object.assign(new Error("実験の結果を読み取れなかった。"), { hint: "もう一度引いてみよう。うまくいかないときはデモでも試せる。" });
    }
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
    setStatus("3つの偶然を、実験に変えている…", "busy");
    if (!await revealResult(result, requestId)) return;
    state.result = result;
    state.count += 1;
    $("experiment-number").textContent = `EXPERIMENT — ${String(state.count).padStart(3, "0")}`;
    document.querySelector(".machine").classList.add("is-complete");
    $("application-text").textContent = result.application;
    $("result-source").textContent = result.source === "local" ? `生成元：ローカルLLM / ${result.model || $("model-select").value}` : "生成元：デモ / 準備済みサンプル";
    $("prompt-text").value = result.prompt;
    $("result-actions").hidden = false;
    $("copy-label").textContent = "この実験の依頼文をコピー";
    window.dispatchEvent(new CustomEvent("roulette:result", { detail: result }));
    setStatus("実験、確定！ 機能の説明を読んで、つくりはじめよう。");
    playTone("complete");
    confetti();
  } catch (error) {
    if (state.requestId !== requestId || error.name === "AbortError") return;
    resetCards();
    showError(error);
  } finally {
    if (state.requestId === requestId) {
      state.controller = null;
      setBusy(false);
    }
  }
}

function setMode(mode) {
  if (state.busy || (mode === "local" && state.demoOnly)) return;
  state.mode = mode;
  document.querySelectorAll('input[name="generation-mode"]').forEach((input) => { input.checked = input.value === mode; });
  clearError();
  if (mode === "local" && !state.models.length) $("connection-settings").open = true;
  setStatus(mode === "demo" ? "デモモード。準備済みの実験を、すぐに引ける。" : state.models.length ? "ローカルLLMモード。選んだモデルがお題を考える。" : "ローカルLLMモード。まずは接続を確認しよう。");
  updateControls();
  saveConnectionPreferences();
}

function updateModelNote() {
  const model = state.models.find((item) => item.id === $("model-select").value);
  if (!model) return;
  const loaded = model.loaded === true ? "ロード済み" : model.loaded === false ? "未ロード候補" : "ロード状態未確認";
  $("connection-summary").textContent = `接続済み · ${loaded}`;
  $("connection-message").dataset.state = "ready";
  if (model.loaded === false) $("connection-message").textContent = "未ロードのモデル。LM Studioで読み込もう。設定によっては、生成時に自動で読み込まれる。";
  else if (model.loaded !== true) $("connection-message").textContent = "サーバーに接続できた。ロード状態はLM Studioの画面で確認してね。";
  else $("connection-message").textContent = "ロード済みのモデルを選択中。生成元を「ローカルLLM」にすると、このモデルがお題を考える。";
  if (state.mode === "local") setStatus("ローカルLLMモード。選んだモデルがお題を考える。");
  updateControls();
}

async function connectModels() {
  if (state.busy || state.modelsBusy || state.demoOnly) return;
  const base = localBaseUrl($("base-url-input").value);
  if (base) {
    if (state.connectionBase !== base) state.preferredModel = "";
    state.connectionBase = base;
    state.reconnectOnLoad = true;
    saveConnectionPreferences();
  }
  state.modelsBusy = true;
  state.models = [];
  $("model-select").replaceChildren(new Option("接続を確認している…", ""));
  $("connection-summary").textContent = "確認中";
  $("connection-message").textContent = "LM Studioのサーバーへ接続して、モデル一覧を取得している…";
  $("connection-message").dataset.state = "ready";
  $("connect-button").textContent = "確認中…";
  updateControls();
  try {
    const response = await apiRequest("/api/models", { method: "POST", body: JSON.stringify({ base_url: $("base-url-input").value.trim() }) });
    state.models = (response.models || []).filter((model) => model.type !== "embedding");
    if (response.base_url) $("base-url-input").value = response.base_url;
    $("model-select").replaceChildren();
    if (!state.models.length) {
      $("model-select").append(new Option("利用できるモデルがない", ""));
      $("connection-summary").textContent = "接続済み · モデルなし";
      $("connection-message").textContent = response.message || "サーバーには接続できた。LM Studioで生成用のモデルを準備して、もう一度接続確認しよう。";
    } else {
      const sortedModels = [...state.models].sort((a, b) => Number(b.loaded === true) - Number(a.loaded === true));
      for (const model of sortedModels) {
        const loaded = model.loaded === true ? "ロード済み" : model.loaded === false ? "未ロード" : "状態未確認";
        $("model-select").append(new Option(`${model.name || model.id} (${loaded})`, model.id));
      }
      if (state.preferredModel && !state.models.some((model) => model.id === state.preferredModel)) {
        $("model-select").prepend(new Option("前のモデルが見つからない。選び直してね。", ""));
        $("model-select").value = "";
        $("connection-summary").textContent = "接続済み · モデル選び直し";
        $("connection-message").textContent = "保存したモデルが一覧にない。LM Studioで準備するか、別のモデルを選んでね。";
        $("connection-settings").open = true;
        if (state.mode === "local") setStatus("接続できた。お題を考えるモデルを選び直してね。");
      } else {
        if (state.preferredModel) $("model-select").value = state.preferredModel;
        state.preferredModel = $("model-select").value;
        updateModelNote();
        saveConnectionPreferences();
      }
    }
  } catch (error) {
    $("model-select").replaceChildren(new Option("接続確認でモデルを取得", ""));
    $("connection-summary").textContent = "接続できなかった";
    $("connection-message").textContent = `${error.message} ${error.hint || "LM Studioのサーバーが起動しているか確認しよう。"}`;
    $("connection-message").dataset.state = "error";
    $("connection-settings").open = true;
    if (state.mode === "local") setStatus("設定は保持しているよ。LM Studioの接続を確認しよう。", "error");
  } finally {
    state.modelsBusy = false;
    $("connect-button").textContent = "接続確認";
    updateControls();
  }
}

async function copyPrompt() {
  if (!state.result) return;
  clearTimeout(copyResetTimer);
  try {
    if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
    await navigator.clipboard.writeText(state.result.prompt);
    $("copy-label").textContent = "コピーした！ Codexに貼り付けよう";
    copyResetTimer = setTimeout(() => { $("copy-label").textContent = "この実験の依頼文をコピー"; }, 3000);
  } catch {
    $("prompt-details").open = true;
    $("prompt-text").focus();
    $("prompt-text").select();
    $("copy-label").textContent = "依頼文を選択した。手動でコピーしてね";
  }
}

function popoverSection(title, body) {
  const section = textElement("section", "", "popover-section");
  section.append(textElement("h3", title), textElement("p", readable(body)));
  return section;
}

function positionPopover() {
  if (!popoverTrigger || $("feature-popover").hidden) return;
  const panel = $("feature-popover");
  const anchor = popoverTrigger.getBoundingClientRect();
  const margin = 14;
  const width = panel.offsetWidth;
  const height = panel.offsetHeight;
  const viewportHeight = window.innerHeight;
  const left = Math.min(Math.max(margin, anchor.left), window.innerWidth - width - margin);
  let top = anchor.bottom + 10;
  if (top + height > viewportHeight - margin && anchor.top - height - 10 >= margin) top = anchor.top - height - 10;
  top = Math.max(margin, Math.min(top, viewportHeight - height - margin));
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}

function openPopover(trigger, feature, pinned = false) {
  if (!feature || trigger.disabled) return;
  clearTimeout(popoverCloseTimer);
  if (popoverTrigger && popoverTrigger !== trigger) popoverTrigger.setAttribute("aria-expanded", "false");
  const sameTrigger = popoverTrigger === trigger;
  popoverTrigger = trigger;
  popoverFeature = feature;
  popoverPinned = pinned || (popoverPinned && sameTrigger);
  trigger.setAttribute("aria-expanded", "true");
  $("popover-title").textContent = feature.name;
  const content = $("popover-content");
  content.replaceChildren();
  content.append(popoverSection("何ができる？", feature.description));
  const application = state.result?.feature_id === feature.id ? state.result.application : feature.sample?.application;
  if (application) content.append(popoverSection(state.result?.feature_id === feature.id ? "今回どう使う？ · 生成された案" : "使い方の例 · サンプル", application));
  content.append(popoverSection("必要な準備", feature.requirements));
  const effort = Array.isArray(feature.effort_minutes) ? `${feature.effort_minutes.join("〜")}分` : `${feature.effort_minutes || "確認中"}${feature.effort_minutes ? "分" : ""}`;
  content.append(popoverSection("利用条件・時間の目安", `${readable(feature.availability)}\n実験の目安：${effort}`));
  const official = textElement("section", "", "popover-section");
  official.append(textElement("h3", "公式情報"));
  try {
    const url = new URL(feature.source_url);
    if (["https:", "http:"].includes(url.protocol)) {
      const link = textElement("a", "公式ページを開く ↗");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      official.append(link);
    }
  } catch { /* URLが不正ならリンクを作らず、確認日だけを表示する。 */ }
  official.append(textElement("p", `発表：${feature.announced_at || "確認中"} / 確認：${feature.verified_at || "確認中"}`, "popover-dates"));
  content.append(official);
  $("feature-popover").hidden = false;
  positionPopover();
}

function closePopover(restoreFocus = false) {
  clearTimeout(popoverCloseTimer);
  const trigger = popoverTrigger;
  trigger?.setAttribute("aria-expanded", "false");
  $("feature-popover").hidden = true;
  popoverTrigger = null;
  popoverFeature = null;
  popoverPinned = false;
  if (restoreFocus && trigger && !trigger.disabled) {
    suppressPopoverFocus = true;
    trigger.focus();
    queueMicrotask(() => { suppressPopoverFocus = false; });
  }
}

function schedulePopoverClose() {
  clearTimeout(popoverCloseTimer);
  if (popoverPinned) return;
  popoverCloseTimer = setTimeout(() => {
    const panel = $("feature-popover");
    const focused = panel.contains(document.activeElement) || document.activeElement === popoverTrigger;
    const hovered = panel.matches(":hover") || popoverTrigger?.matches(":hover");
    if (!focused && !hovered) closePopover();
  }, 180);
}

function bindPopover(trigger, getFeature) {
  trigger.addEventListener("pointerenter", (event) => { if (event.pointerType !== "touch") openPopover(trigger, getFeature()); });
  trigger.addEventListener("pointerleave", schedulePopoverClose);
  trigger.addEventListener("focus", () => { if (!suppressPopoverFocus) openPopover(trigger, getFeature()); });
  trigger.addEventListener("blur", schedulePopoverClose);
  trigger.addEventListener("click", () => {
    if (popoverPinned && popoverTrigger === trigger) closePopover();
    else openPopover(trigger, getFeature(), true);
  });
}

async function init() {
  $("motion-toggle").checked = motionPreference.matches;
  updateMotion();
  motionPreference.addEventListener("change", updateMotion);
  $("motion-toggle").addEventListener("change", updateMotion);
  $("sound-toggle").addEventListener("change", () => {
    state.audioVersion += 1;
    if ($("sound-toggle").checked) playTone("enable");
    else { stopTones(); soundStatus("", "off"); }
  });
  $("draw-button").addEventListener("click", generateExperiment);
  $("cancel-button").addEventListener("click", cancelGeneration);
  $("connect-button").addEventListener("click", connectModels);
  $("model-select").addEventListener("change", () => {
    state.preferredModel = $("model-select").value;
    updateModelNote();
    saveConnectionPreferences();
  });
  $("copy-button").addEventListener("click", copyPrompt);
  $("demo-fallback").addEventListener("click", () => { setMode("demo"); generateExperiment(); });
  $("base-url-input").addEventListener("input", () => {
    if (state.models.length) {
      state.models = [];
      $("model-select").replaceChildren(new Option("接続確認でモデルを取得", ""));
      $("connection-summary").textContent = "再接続が必要";
      updateControls();
    }
    const base = localBaseUrl($("base-url-input").value);
    if (base) {
      if (state.connectionBase !== base) { state.preferredModel = ""; state.reconnectOnLoad = false; }
      state.connectionBase = base;
      saveConnectionPreferences();
    }
  });
  document.querySelectorAll('input[name="generation-mode"]').forEach((input) => input.addEventListener("change", () => setMode(input.value)));
  bindPopover($("feature-info"), () => state.result?.feature);
  $("popover-close").addEventListener("click", () => closePopover(true));
  $("feature-popover").addEventListener("pointerenter", () => clearTimeout(popoverCloseTimer));
  $("feature-popover").addEventListener("pointerleave", schedulePopoverClose);
  $("feature-popover").addEventListener("focusout", schedulePopoverClose);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("feature-popover").hidden) { event.preventDefault(); closePopover(true); } });
  document.addEventListener("click", (event) => { if (popoverTrigger && !$("feature-popover").contains(event.target) && !popoverTrigger.contains(event.target)) closePopover(); });
  window.addEventListener("resize", positionPopover);
  window.addEventListener("scroll", positionPopover, { passive: true });

  const results = await Promise.allSettled([apiRequest("/api/features"), apiRequest("/api/config")]);
  if (results[1].status === "fulfilled") {
    const config = results[1].value;
    $("base-url-input").value = config.lm_base_url || "http://127.0.0.1:1234/v1";
    state.timeoutSeconds = config.generation_timeout_seconds || 30;
    state.demoOnly = Boolean(config.demo_only);
    if (config.auth_configured) {
      $("auth-note").textContent = "認証トークンはPython側に設定済み。ブラウザには保存しない。";
      $("auth-note").hidden = false;
    }
    if (state.demoOnly) {
      $("connection-summary").textContent = "テスト用デモ環境";
      $("connection-message").textContent = "独立したテスト環境で起動中。外部のLM Studioには接続しない。";
    }
  }
  if (results[0].status === "rejected") {
    updateControls();
    showError(results[0].reason);
    return;
  }
  state.features = results[0].value.features || [];
  state.selectedIds = new Set(state.features.filter((feature) => feature.default_enabled).map((feature) => feature.id));
  renderFeatureOptions();
  state.connectionBase = localBaseUrl($("base-url-input").value) || "";
  const saved = readConnectionPreferences();
  if (saved && !state.demoOnly) {
    state.connectionBase = saved.baseUrl;
    state.preferredModel = saved.modelId;
    state.reconnectOnLoad = saved.reconnect;
    $("base-url-input").value = saved.baseUrl;
  }
  setMode(saved && !state.demoOnly ? saved.mode : "demo");
  if (!state.demoOnly && results[1].status === "fulfilled" && state.reconnectOnLoad) await connectModels();
}

// 注釈APIなどから、現在の実験と色設定へアクセスできる小さな入口。
window.rouletteApp = {
  getCurrentResult: () => state.result ? structuredClone(state.result) : null,
  getFeatures: () => structuredClone(state.features),
  setAccent: (color) => { if (CSS.supports("color", color)) document.documentElement.style.setProperty("--accent-main", color); },
};

init().catch((error) => showError(error));
