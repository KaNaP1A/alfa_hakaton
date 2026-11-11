"use strict";

const $ = (id) => document.getElementById(id);
const input = $("query");
const state = {
  ready: false, composing: false, selected: null, options: [], active: -1,
  suggestionVersion: 0, searchVersion: 0, timer: null,
  suggestionController: null, searchController: null, result: null,
};
const kindNames = { course: "Курс", article: "Статья", document: "Документ", glossary: "Термин", podcast: "Подкаст", webinar: "Вебинар", title: "Материал", lesson: "Урок курса", phrase: "Фраза", topics: "Тема", tags: "Тег", industries: "Сфера" };
const accessNames = { open: "Открытый доступ", paid: "Платный", subscription: "По подписке", unknown: "Доступ не уточнён" };

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
  clearSelection();
  cancelSuggestions();
  cancelSearch();
  message("");
  if (state.result) renderResults(state.result); else $("results-section").hidden = true;
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
function diagnostics(item) {
  const box = element("details", "diagnostic");
  box.append(element("summary", "", "Как материал оказался в выдаче"));
  const scores = element("div", "score-grid");
  for (const [key, label] of [["bm25", "BM25"], ["cosine", "Близость по смыслу"], ["rrf", "RRF"]]) {
    if (item.scores[key] === null) continue;
    const cell = element("div", "score-box", label);
    cell.append(element("b", "", String(item.scores[key])));
    scores.append(cell);
  }
  box.append(scores, element("p", "", `Совпавшие слова: ${item.matched_words.join(", ") || "нет буквальных совпадений"}`), element("p", "", "Оценки служат для сравнения кандидатов. Это не вероятность покупки и не гарантия полезности."), element("pre", "", JSON.stringify(item, null, 2)));
  return box;
}
function renderResults(data) {
  state.result = data;
  $("welcome").hidden = true;
  $("results-section").hidden = false;
  $("results-title").textContent = data.results.length ? `Найдено материалов: ${data.results.length}` : "Пока ничего не нашли";
  $("results-query").textContent = `По запросу «${data.query}»${data.selection ? ` · ${data.selection.label}` : ""}`;
  $("results-note").textContent = data.results.length ? "Это тестовая выдача: проверьте, насколько материалы подходят к вашей задаче." : "Попробуйте другую формулировку, уберите фильтр типа материала или уточнение.";
  if (data.unmatched_query_terms.length && data.results.length) {
    $("results-note").textContent += ` Без буквального совпадения: ${data.unmatched_query_terms.join(", ")}.`;
  }
  $("copy-json").hidden = !$("diagnostics").checked;
  const list = $("results");
  list.replaceChildren();
  if (!data.results.length) list.append(element("div", "empty-state", "В выбранном режиме подходящих совпадений нет. Измените запрос или настройки поиска."));
  data.results.forEach((item, index) => {
    const card = element("article", "result-card");
    const meta = element("div", "card-meta");
    meta.append(element("span", `kind-badge ${item.kind}`, kindNames[item.kind] || item.kind), element("span", "", accessNames[item.access_type] || "Доступ не уточнён"), element("span", "rank", `${String(index + 1).padStart(2, "0")} /`));
    card.append(meta, element("h3", "", item.title));
    if (item.description) {
      const text = item.description;
      const cut = text.lastIndexOf(" ", 260);
      const preview = text.length > 280 ? `${text.slice(0, cut > 180 ? cut : 260)}…` : text;
      const description = element("p", "card-description", preview);
      card.append(description);
      if (preview !== text) {
        const expand = element("button", "description-toggle", "Показать описание");
        expand.type = "button";
        expand.setAttribute("aria-expanded", "false");
        expand.addEventListener("click", () => {
          const opened = expand.getAttribute("aria-expanded") !== "true";
          expand.setAttribute("aria-expanded", String(opened));
          expand.textContent = opened ? "Свернуть описание" : "Показать описание";
          description.textContent = opened ? text : preview;
        });
        card.append(expand);
      }
    }
    const tags = element("div", "card-tags");
    for (const tag of [...new Set([...item.topics, ...item.tags])].slice(0, 5)) tags.append(element("span", "", tag));
    card.append(tags);
    if (item.selection_match) card.append(element("p", "selection-reason", "Связан с выбранным вами уточнением"));
    if (item.matched_lessons.length) card.append(element("div", "lesson-match", `В программе курса: ${item.matched_lessons.map((lesson) => lesson.title).join(" · ")}`));
    if (item.canonical_url) {
      const url = new URL(item.canonical_url);
      if (url.protocol === "https:" && url.hostname === "kurs.alfabank.ru" && !url.username && !url.password) {
        const link = element("a", "card-link", "Открыть материал ↗");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        card.append(link);
      }
    }
    if ($("diagnostics").checked) card.append(diagnostics(item));
    list.append(card);
  });
}
async function search() {
  if (!state.ready || state.composing) return;
  const query = input.value.trim();
  if (!query) { message("Опишите задачу, чтобы начать поиск."); input.focus(); return; }
  cancelSuggestions();
  cancelSearch();
  const version = state.searchVersion;
  state.searchController = new AbortController();
  const params = { q: query, mode: $("mode").value, top: $("top").value };
  if ($("kind").value) params.kind = $("kind").value;
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
    renderResults(data);
  } catch (error) {
    if (error.name === "AbortError" || version !== state.searchVersion) return;
    if (error.status === 400 && state.selected) {
      clearSelection();
      message("Уточнение больше не доступно или параметры изменились. Выберите новую подсказку и повторите поиск.");
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
$("clear-selection").addEventListener("click", () => { clearSelection(); void search(); });
document.addEventListener("pointerdown", (event) => { if (!$("search-form").contains(event.target)) cancelSuggestions(); });
for (const button of document.querySelectorAll("[data-query]")) button.addEventListener("click", () => { input.value = button.dataset.query; changed(); input.focus(); void search(); });
for (const id of ["mode", "kind", "top"]) $(id).addEventListener("change", () => { if (input.value.trim()) void search(); });
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
    state.ready = true;
    const hybrid = $("mode").querySelector('[value="hybrid"]');
    hybrid.disabled = !health.hybrid_available;
    $("mode").querySelector('[value="catboost"]').disabled = !health.catboost_available;
    $("mode").value = health.hybrid_available ? "hybrid" : "bm25";
    $("mode-help").textContent = health.hybrid_available ? "Смысловая модель доступна и загружена на этом компьютере." : "Смысловой поиск не загружен. Доступен поиск по словам.";
    $("connection").replaceChildren(element("i"), document.createTextNode("Сервер подключён"));
    $("catalog-caption").textContent = `${new Intl.NumberFormat("ru-RU").format(health.catalog_count)} материалов в локальном каталоге`;
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
void initialize();
