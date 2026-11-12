"use strict";

const $ = (id) => document.getElementById(id);
const input = $("query");
const state = {
  ready: false, mode: "ensemble", composing: false, selected: null, options: [], active: -1,
  suggestionVersion: 0, searchVersion: 0, timer: null,
  suggestionController: null, searchController: null, result: null, generation: null, suppressClarification: false, searchId: null, clarification: null,
};
const kindNames = { course: "Курс", article: "Статья", document: "Документ", glossary: "Термин", podcast: "Подкаст", webinar: "Вебинар", title: "Материал", lesson: "Урок курса", phrase: "Фраза", topics: "Тема", tags: "Тег", industries: "Сфера" };
const accessNames = { open: "В выгрузке: открытый тип · цена не проверена", paid: "В выгрузке: платный тип · условия не проверены", subscription: "В выгрузке: подписка · доступ не проверен", unknown: "Доступ и цена не уточнены" };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function message(text) {
  $("message").textContent = text;
  $("message").hidden = !text;
}
async function api(path, params, signal) {
  const response = await fetch(`${path}?${new URLSearchParams(params)}`, { signal });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function closeSuggestions() {
  $("suggestion-panel").hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  state.active = -1;
}
function cancelSuggestions() {
  clearTimeout(state.timer);
  state.suggestionVersion += 1;
  state.suggestionController?.abort();
  closeSuggestions();
}
function clearSelection() {
  state.selected = null;
  state.clarification = null;
  $("selected-wrap").hidden = true;
  $("selected-label").textContent = "";
}
function setBusy(busy) {
  $("search-button").disabled = !state.ready;
  $("search-button").replaceChildren(document.createTextNode(busy ? "Ищем…" : "Найти "), element("span", "", busy ? "" : "↗"));
  $("results").setAttribute("aria-busy", String(busy));
}
function cancelSearch() {
  state.searchVersion += 1;
  state.searchController?.abort();
  setBusy(false);
}
function renderSuggestions(data) {
  state.options = [];
  state.active = -1;
  const list = $("suggestion-list");
  list.replaceChildren();
  for (const [label, items] of [["Материалы и фразы", data.completions], ["Уточните направление", data.related_topics]]) {
    if (!items.length) continue;
    const group = element("div", "suggestion-group", label);
    group.setAttribute("role", "presentation");
    list.append(group);
    for (const item of items) {
      const index = state.options.length;
      state.options.push({ ...item, generation: data.generation });
      const button = element("button", "suggestion-option");
      button.type = "button";
      button.id = `suggestion-${index}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", "false");
      button.tabIndex = -1;
      button.append(element("span", "option-icon", item.kind === "topics" ? "#" : "↗"), element("span", "option-label", item.label), element("span", "option-kind", kindNames[item.kind] || "Материал"));
      button.addEventListener("pointerdown", (event) => event.preventDefault());
      button.addEventListener("click", () => choose(index));
      list.append(button);
    }
  }
  const hasOptions = state.options.length > 0;
  $("suggestion-panel").hidden = !hasOptions;
  input.setAttribute("aria-expanded", String(hasOptions));
  input.removeAttribute("aria-activedescendant");
  $("suggestion-caption").textContent = data.typo_tolerant_match ? "Подсказки с учётом возможной опечатки" : "Подсказки из каталога";
  $("input-help").textContent = data.status === "no_match" ? "Подсказок пока нет. Можно уточнить запрос или нажать «Найти»." : data.status === "insufficient_input" ? "Начните писать — предложим материалы и связанные темы." : "Выберите материал или тему — либо ищите своим запросом.";
}
async function suggest() {
  const query = input.value;
  const version = ++state.suggestionVersion;
  state.suggestionController?.abort();
  const controller = new AbortController();
  state.suggestionController = controller;
  try {
    const data = await api("/suggest", { q: query, limit: "5" }, controller.signal);
    if (version !== state.suggestionVersion || input.value !== query) return;
    renderSuggestions(data);
  } catch (error) {
    if (error.name === "AbortError" || version !== state.suggestionVersion) return;
    closeSuggestions();
    $("input-help").textContent = "Не удалось загрузить подсказки. Обычный поиск доступен через «Найти».";
  }
}
function changed() {
  state.suppressClarification = false;
  clearSelection();
  cancelSuggestions();
  cancelSearch();
  message("");
  if (state.result) { renderResults(state.result); if (input.value.trim() !== state.result.query) $("clarification").hidden = true; } else $("results-section").hidden = true;
  $("welcome").hidden = Boolean(state.result);
  if (!input.value.trim()) {
    $("input-help").textContent = "Начните писать — предложим материалы и связанные темы.";
    return;
  }
  if (!state.composing && state.ready) state.timer = setTimeout(suggest, 150);
}
function choose(index) {
  const item = state.options[index];
  if (!item) return;
  clearSelection();
  state.selected = item;
  $("selected-label").textContent = item.label;
  $("selected-wrap").hidden = false;
  cancelSuggestions();
  input.focus();
  void search();
}
function activate(index) {
  state.active = (index + state.options.length) % state.options.length;
  for (let i = 0; i < state.options.length; i += 1) {
    $(`suggestion-${i}`).setAttribute("aria-selected", String(i === state.active));
  }
  const option = $(`suggestion-${state.active}`);
  input.setAttribute("aria-activedescendant", option.id);
  option.scrollIntoView({ block: "nearest" });
}
function diagnostics(item, data) {
  const box = element("details", "diagnostic");
  box.append(element("summary", "", "Как материал оказался в выдаче"));
  const scores = element("div", "score-grid");
  for (const [key, label] of [["bm25", "BM25"], ["cosine", "Близость по смыслу"], ["rrf", "RRF"], ["catboost", "CatBoost (5 признаков)"], ["final_score", "Итоговый скор"]]) {
    if (item.scores[key] === null) continue;
    const cell = element("div", "score-box", label);
    cell.append(element("b", "", String(item.scores[key])));
    scores.append(cell);
  }
  if (data.ensemble_weights) {
    const names = {bm25:"BM25", hybrid:"Гибрид", catboost:"CatBoost"};
    const weights = Object.entries(data.ensemble_weights).map(([name, weight]) => `${names[name] || name}: ${weight}`).join(" · ");
    const positions = Object.entries(item.ensemble_ranks).map(([name, rank]) => `${names[name] || name}: ${rank}`).join(" · ");
    box.append(element("p", "", `Веса: ${weights}`), element("p", "", `Позиции методов: ${positions}`));
    if (item.selection_match) box.append(element("p", "", `Множитель выбранного уточнения: ${item.selection_multiplier}`));
  }
  box.append(scores, element("p", "", `Совпавшие слова: ${item.matched_words.join(", ") || "нет буквальных совпадений"}`), element("p", "", "Оценки служат для сравнения кандидатов. Это не вероятность покупки и не гарантия полезности."), element("pre", "", JSON.stringify(item, null, 2)));
  return box;
}
function localProfile() {
  try {
    const profile = JSON.parse(localStorage.getItem("alfa_profile_v1") || "{}");
    if (!profile || typeof profile !== "object") throw new Error("invalid profile");
    return { generation: profile.generation || state.generation, categories: Array.isArray(profile.categories) ? profile.categories : [], viewed: Array.isArray(profile.viewed) ? profile.viewed : [] };
  } catch { return { generation: state.generation, categories: [], viewed: [] }; }
}
function saveProfile(profile) { try { localStorage.setItem("alfa_profile_v1", JSON.stringify(profile)); } catch { /* Storage can be disabled. */ } }
function event(type, extra = {}) {
  try {
    let session = sessionStorage.getItem("alfa_session_v1");
    if (!session) { session = crypto.randomUUID(); sessionStorage.setItem("alfa_session_v1", session); }
    const events = JSON.parse(localStorage.getItem("alfa_events_v1") || "[]");
    events.push({ event_id: crypto.randomUUID(), timestamp: new Date().toISOString(), session_id: session, type, generation: state.generation, ranking: "ensemble_experimental", experiment_variant: null, ...extra });
    localStorage.setItem("alfa_events_v1", JSON.stringify(events.slice(-500)));
  } catch { /* Analytics must never prevent search. */ }
}
function remember(item, type = "item_interest") {
  const profile = localProfile();
  if (profile.generation !== state.generation) { profile.generation = state.generation; profile.viewed = []; }
  profile.viewed = [...profile.viewed.filter((key) => key !== item.entity_key), item.entity_key].slice(-50);
  saveProfile(profile);
  const position = state.result?.results.findIndex((row) => row.entity_key === item.entity_key) ?? -1;
  event(type, { item_id: item.entity_key, search_id: position >= 0 ? state.searchId : null, position: position >= 0 ? position + 1 : null });
  void loadHome();
}
async function loadHome() {
  if (!state.generation) return;
  const profile = localProfile();
  if (profile.generation !== state.generation) { profile.generation = state.generation; profile.viewed = []; saveProfile(profile); }
  if (!profile.categories.length && !profile.viewed.length) { $("home-recommendations").hidden = true; return; }
  try {
    const response = await fetch("/recommend", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(profile)});
    if (!response.ok) throw new Error("recommendations unavailable");
    const data = await response.json();
    const container = $("home-cards"); container.replaceChildren();
    data.results.forEach((item) => {
      const card = element("article", "result-card");
      card.append(element("div", "card-meta", `${kindNames[item.kind] || "Материал"} · ${accessNames[item.access_type] || "Доступ не уточнён"}`), element("h3", "", item.title), element("p", "evidence-reason", item.reason));
      if (item.promotion?.text) card.append(element("p", "card-description", item.promotion.text));
      if (item.canonical_url) {
        try { const url = new URL(item.canonical_url); if (url.protocol === "https:" && url.hostname === "kurs.alfabank.ru" && !url.username && !url.password) { const link = element("a", "card-link", "Открыть материал ↗"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.addEventListener("click", () => remember(item, "item_open")); card.append(link); } } catch { /* Unverified URL is not displayed. */ }
      }
      container.append(card);
    });
    $("home-recommendations").hidden = !data.results.length || !$("results-section").hidden;
    if (data.results.length && !$("home-recommendations").hidden) event("recommendation_impression", { item_ids: data.results.map((item) => item.entity_key) });
  } catch { $("home-recommendations").hidden = true; }
}
function renderClarification(data) {
  const box = $("clarification"); box.replaceChildren();
  const suggestion = data.clarification;
  if (!suggestion || state.suppressClarification) { box.hidden = true; return; }
  box.hidden = false;
  box.append(element("strong", "", suggestion.question), element("p", "", "Выберите следующий шаг или пропустите вопрос."));
  const submit = (option, text = "") => {
    if (input.value.trim() !== data.query || (!option && !text.trim())) return;
    clearSelection();
    state.clarification = option ? { token: option.token, label: option.label } : { text: text.trim(), label: text.trim() };
    $("selected-label").textContent = state.clarification.label;
    $("selected-wrap").hidden = false;
    state.suppressClarification = true;
    event("clarification_answered", { answer_type: option ? "option" : "free_text" });
    void search();
  };
  for (const option of suggestion.options) {
    const button = element("button", "clarification-option", option.label); button.type = "button";
    button.addEventListener("click", () => submit(option)); box.append(button);
  }
  const field = element("input", "clarification-input"); field.placeholder = "Или напишите своё уточнение"; field.setAttribute("aria-label", "Своё уточнение"); field.maxLength = 100; box.append(field);
  const apply = element("button", "clarification-option", "Уточнить"); apply.type = "button"; apply.addEventListener("click", () => submit(null, field.value)); box.append(apply);
  const skip = element("button", "text-button", "Пропустить"); skip.type = "button"; skip.addEventListener("click", () => { box.hidden = true; state.suppressClarification = true; event("clarification_skipped"); }); box.append(skip);
}
function appendCard(item, index, cards, data) {
  const card = element("article", "result-card");
  const meta = element("div", "card-meta");
  meta.append(element("span", `kind-badge ${item.kind}`, kindNames[item.kind] || item.kind), element("span", "", accessNames[item.access_type] || "Доступ не уточнён"), element("span", "rank", `${String(index + 1).padStart(2, "0")} /`));
  card.append(meta, element("h3", "", item.title));
  if (item.promotion?.text) card.append(element("p", "evidence-reason", item.promotion.text));
  const tags = element("div", "card-tags");
  for (const tag of [...new Set([...item.topics, ...item.tags])].slice(0, 5)) tags.append(element("span", "", tag));
  card.append(tags);
  if (item.description) { const details = element("details", "description-details"); details.append(element("summary", "", "О материале"), element("p", "card-description", item.description)); card.append(details); }
  if (item.canonical_url) {
    try {
      const url = new URL(item.canonical_url);
      if (url.protocol === "https:" && url.hostname === "kurs.alfabank.ru" && !url.username && !url.password) {
        const link = element("a", "card-link", "Открыть материал ↗"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.addEventListener("click", () => remember(item, "item_open")); card.append(link);
      }
    } catch { /* No guessed links. */ }
  }
  const interest = element("button", "text-button interest-button", "Учесть мой интерес"); interest.type = "button";
  interest.addEventListener("click", () => { remember(item); interest.textContent = "Интерес учтён ✓"; interest.disabled = true; }); card.append(interest);
  if ($("diagnostics").checked) card.append(diagnostics(item, data));
  cards.append(card);
}
function renderResults(data) {
  state.result = data;
  $("welcome").hidden = true; $("home-recommendations").hidden = true; $("results-section").hidden = false;
  const constrained = Boolean(data.confidence?.reason);
  $("results-title").textContent = constrained ? "Подборка с непроверенными условиями" : data.results.length ? `Подобрали материалов: ${data.results.length}` : "Точного материала пока не нашли";
  $("results-query").textContent = data.focus ? `Вы выбрали: ${data.focus.label}` : `По запросу «${data.query}»${data.selection ? ` · ${data.selection.label}` : ""}`;
  $("results-note").textContent = data.focus?.kind === "material" ? "Ниже — материалы по выбранному шагу." : data.results.length ? "Выберите материал и начните с удобного вам шага." : "Попробуйте уточнить задачу или выберите один из предложенных шагов.";
  const rules = data.query_rules;
  if (rules?.unsupported_constraints?.includes("price")) $("results-note").textContent += " Цены не подтверждены: бесплатность материалов проверить не удалось.";
  if (rules?.unsupported_constraints?.includes("experience")) $("results-note").textContent += " Требования к опыту не подтверждены.";
  if (rules?.unsupported_constraints?.includes("duration")) $("results-note").textContent += " Длительность материалов не подтверждена.";
  if (data.confidence?.reason === "unresolved_negation") $("results-note").textContent += " Не удалось надёжно учесть отрицание. Проверьте условия перед выбором материала.";
  $("copy-json").hidden = !$("diagnostics").checked;
  const list = $("results"); list.replaceChildren();
  let cards = list;
  if (constrained && data.results.length) { const details = element("details", "uncertain-results"); details.append(element("summary", "", "Посмотреть варианты и проверить условия")); cards = element("div", "uncertain-cards"); details.append(cards); list.append(details); }
  renderClarification(data);
  data.results.forEach((item, index) => appendCard(item, index, cards, data));
  if (data.alternatives?.length) {
    const details = element("details", "uncertain-results"); details.append(element("summary", "", "Посмотреть близкие темы"));
    const alternatives = element("div", "uncertain-cards"); alternatives.append(element("p", "", "Это возможные альтернативы: они могут покрывать лишь часть вашей задачи."));
    data.alternatives.forEach((item, index) => appendCard(item, index, alternatives, data)); details.append(alternatives); list.append(details);
  }
  if (!data.results.length && !data.alternatives?.length) list.append(element("div", "empty-state", "Подходящих материалов для этой формулировки пока нет. Уточните запрос — список не дополняется случайными карточками."));
}
async function search() {
  if (!state.ready || state.composing) return;
  const query = input.value.trim();
  if (!query) { message("Опишите задачу, чтобы начать поиск."); input.focus(); return; }
  cancelSuggestions();
  cancelSearch();
  const version = state.searchVersion;
  state.searchController = new AbortController();
  const params = { q: query, mode: state.mode, top: $("top").value };
  if ($("kind").value) params.kind = $("kind").value;
  if (state.clarification?.token) params.clarification_token = state.clarification.token;
  if (state.clarification?.text) params.clarification_text = state.clarification.text;
  if (state.selected) { params.selection_id = state.selected.id; params.selection_generation = state.selected.generation; }
  message(""); setBusy(true);
  $("welcome").hidden = true;
  $("results-section").hidden = false;
  $("results-title").textContent = "Ищем материалы…";
  $("results-query").textContent = `По запросу «${query}»`;
  $("results-note").textContent = "";
  $("copy-json").hidden = true;
  $("results").replaceChildren(element("div", "skeleton"), element("div", "skeleton"));
  try {
    const data = await api("/search", params, state.searchController.signal);
    if (version !== state.searchVersion) return;
    state.searchId = crypto.randomUUID();
    renderResults(data);
    event("search_impression", { search_id: state.searchId, item_ids: data.results.map((item) => item.entity_key), uncertain: data.confidence?.status === "uncertain" });
  } catch (error) {
    if (error.name === "AbortError" || version !== state.searchVersion) return;
    if (error.status === 400 && (state.selected || state.clarification)) {
      clearSelection();
      message("Уточнение больше не доступно или параметры изменились. Выберите новую подсказку и повторите поиск.");
    } else if (error.status === 400) {
      message(`Поиск недоступен: ${error.message}`);
    } else {
      message("Поиск не ответил. Проверьте, запущен ли локальный сервер, и попробуйте ещё раз.");
    }
    if (state.result) renderResults(state.result);
    else { $("results-section").hidden = true; $("welcome").hidden = false; }
  } finally {
    if (version === state.searchVersion) setBusy(false);
  }
}
input.addEventListener("input", changed);
input.addEventListener("compositionstart", () => { state.composing = true; cancelSuggestions(); });
input.addEventListener("compositionend", () => { state.composing = false; changed(); });
input.addEventListener("keydown", (event) => {
  if (event.isComposing || state.composing) return;
  if (event.key === "Escape") { cancelSuggestions(); return; }
  if (!$("suggestion-panel").hidden && state.options.length) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      activate(state.active === -1 ? (event.key === "ArrowDown" ? 0 : state.options.length - 1) : state.active + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter" && state.active !== -1) { event.preventDefault(); choose(state.active); }
  }
});
input.addEventListener("focus", () => { if (input.value.trim() && state.ready && !state.selected) { cancelSuggestions(); state.timer = setTimeout(suggest, 150); } });
$("search-form").addEventListener("submit", (event) => { event.preventDefault(); void search(); });
$("clear-selection").addEventListener("click", () => { clearSelection(); state.suppressClarification = false; void search(); });
document.addEventListener("pointerdown", (event) => { if (!$("search-form").contains(event.target)) cancelSuggestions(); });
for (const button of document.querySelectorAll("[data-query]")) button.addEventListener("click", () => { input.value = button.dataset.query; changed(); input.focus(); void search(); });
for (const id of ["kind", "top"]) $(id).addEventListener("change", () => { if (input.value.trim()) void search(); });
$("diagnostics").addEventListener("change", () => { if (state.result && $("results").getAttribute("aria-busy") !== "true") renderResults(state.result); });
$("copy-json").addEventListener("click", async () => {
  if (!state.result) return;
  try { await navigator.clipboard.writeText(JSON.stringify(state.result, null, 2)); $("copy-json").textContent = "Скопировано ✓"; }
  catch { message("Браузер не разрешил копирование. JSON каждого результата доступен в режиме исследования."); }
  setTimeout(() => { $("copy-json").textContent = "Скопировать JSON"; }, 1800);
});
async function initialize() {
  try {
    const health = await api("/health", {});
    state.generation = health.generation;
    state.mode = health.default_search_mode || "ensemble";
    state.ready = state.mode === "relevance" ? Boolean(health.relevance_available)
      : state.mode === "bm25" ? true
      : state.mode === "hybrid" ? Boolean(health.hybrid_available)
      : state.mode === "catboost" ? Boolean(health.catboost_available)
      : Boolean(health.ensemble_available);
    void loadHome();
    $("mode-help").textContent = state.ready ? "Подбираем материалы по вашей задаче." : "Поиск не готов: запустите сервер с моделью и проверьте артефакты.";
    if (!state.ready) message("Для поиска нужны модель эмбеддингов, CatBoost, векторы и подготовленные веса. См. инструкцию запуска.");
    $("connection").replaceChildren(element("i"), document.createTextNode("Сервер подключён"));
    $("catalog-caption").textContent = `${new Intl.NumberFormat("ru-RU").format(health.searchable_count ?? health.catalog_count)} материалов в локальном каталоге`;
    setBusy(false);
    if (input.value.trim()) changed();
  } catch {
    $("connection").classList.add("offline");
    $("connection").replaceChildren(element("i"), document.createTextNode("Нет соединения"));
    $("catalog-caption").textContent = "Каталог недоступен";
    $("mode-help").textContent = "Сервер не ответил.";
    message("Не удалось подключиться. Запустите локальный сервер и обновите страницу.");
  }
}
$("clear-history").addEventListener("click", () => { const profile = localProfile(); profile.viewed = []; saveProfile(profile); void loadHome(); });
void initialize();
