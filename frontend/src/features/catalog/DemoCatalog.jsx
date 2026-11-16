import React, { useEffect, useMemo, useState } from "react";
import dataUrl from "../../../../data/demo_catalog.json?url";
import { api } from "../../shared/api/index.js";
import { orderDemoItems, filterDemoItems } from "./demoCatalog.js";
import { rankDemoOffers } from "./demoRecommendations.js";
import { kindLabels } from "../../shared/ui/MaterialCard.jsx";
import { TYPES } from "../search/SearchResults.jsx";
import { State } from "../../shared/ui/ResultStates.jsx";

const SIZE = 12;
const ORIGINS = {
  synthetic: "Вымышленный пример",
  public_snapshot: "Публичный снимок Альфы",
  historical_backup: "Снимок бэкапа",
};
const money = (value) => `${value.toLocaleString("ru-RU")} ₽`;

export function DemoCatalog({ onUseModel, onOpenRecommendations }) {
  const [items, setItems] = useState([]);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [kind, setKind] = useState("");
  const [origin, setOrigin] = useState("");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(SIZE);
  const [lastTopic, setLastTopic] = useState(null);
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [budget, setBudget] = useState("");
  const [preferMargin, setPreferMargin] = useState(false);
  const [modelResults, setModelResults] = useState([]);
  const [modelState, setModelState] = useState("");
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(dataUrl)
      .then((response) => {
        if (!response.ok) throw new Error("catalog load failed");
        return response.json();
      })
      .then((data) => {
        if (active) setItems(orderDemoItems(data.items || []));
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => {
      active = false;
    };
  }, [retry]);

  const matches = useMemo(
    () => filterDemoItems(items, { kind, origin, query }),
    [items, kind, origin, query],
  );
  const next =
    lastTopic &&
    items.find(
      (item) =>
        item.origin === "synthetic" &&
        item.kind === "course" &&
        item.topics?.includes(lastTopic),
    );
  const budgetValue = budget.trim() === "" ? null : Number(budget);
  const invalidBudget = budgetValue !== null && (!Number.isInteger(budgetValue) || budgetValue <= 0);
  const ranked = useMemo(
    () => submitted && !invalidBudget
      ? rankDemoOffers(items, { query: submitted, maxPrice: budgetValue, preferMargin, modelResults })
      : [],
    [items, submitted, invalidBudget, budgetValue, preferMargin, modelResults],
  );

  async function searchOffers(event) {
    event.preventDefault();
    const value = draft.trim();
    if (!value || value.length > 300 || invalidBudget) return;
    setSearching(true);
    setModelState("");
    setModelResults([]);
    setSubmitted(value);
    try {
      const response = await api.search({ q: value, top: 50 });
      if (response.mode === "http" || response.mode === "python") {
        setModelResults(response.results || []);
        setModelState("Используется поиск модели; для части курсов связь определена по названию и не подтверждена. Остальные подобраны по словам.");
      } else {
        setModelState("Модель не подключена: показан подбор по словам.");
      }
    } catch {
      setModelState("Поиск модели недоступен: показан подбор по словам.");
    } finally {
      setSearching(false);
    }
  }

  function change(setValue, value) {
    setValue(value);
    setShown(SIZE);
  }

  function card(item, rank) {
    const synthetic = item.origin === "synthetic";
    const offer = item.demo_offer;
    const price =
      offer
        ? `${money(offer.price_rub)} · условная цена`
        : item.price?.status === "fictional_free"
          ? "Бесплатно · условный пример"
          : "Цена не указана";

    return (
      <article className="result-card demo-card" key={item.id}>
        <div className="item-copy">
          <div className="meta">
            <span className="kind">{kindLabels[item.kind] || "Материал"}</span>
            <span className="topic">
              {ORIGINS[item.origin] || "Демо"}
            </span>
          </div>
          <h3>{item.title}</h3>
          <p>{item.description || "Описание не предоставлено."}</p>
          {rank && (
            <p className="demo-reason">
              {rank.modelMatch === "title_candidate" ? "Модель нашла курс с таким названием; связь не подтверждена" : rank.matchedModel ? "Найдена моделью" : "Подобрана по словам запроса"}
              {` · условная прибыль: ${money(rank.margin)}`}
              {preferMargin && rank.originalPosition !== rank.position ? ` · позиция по теме: ${rank.originalPosition}` : ""}
            </p>
          )}
          <div className="item-footer">
            <span className="demo-price">{price}{offer && ` · себестоимость ${money(offer.cost_rub)} (условно)`}</span>
            {synthetic && item.kind === "article" && (
              <button
                className="text-btn"
                onClick={() => setLastTopic(item.topics?.[0])}
              >
                Продолжить тему →
              </button>
            )}
            {!synthetic && item.source_url && (
              <a
                className="text-btn"
                href={item.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Источник ↗
              </a>
            )}
          </div>
          {offer?.reference && <small className="demo-price">Ориентир — цена из снимка; совпадение и актуальность не подтверждены.</small>}
        </div>
      </article>
    );
  }

  if (loadError)
    return (
      <div className="notice" role="alert">
        Не удалось загрузить демонстрационные материалы.
        <button
          className="text-btn"
          onClick={() => {
            setLoadError(false);
            setRetry((value) => value + 1);
          }}
        >
          Повторить
        </button>
      </div>
    );
  if (!items.length) return <State loading />;

  return (
    <section aria-label="Демонстрационный каталог">
      <div className="notice demo-notice">
        <p>
          Демо-каталог показывает открытый снимок и вымышленные примеры; эти
          карточки не передаются модели. Для ранжирования PostgreSQL-материалов
          выберите каталог алгоритма, поиск или персональную подборку.
        </p>
        <div className="demo-actions">
          <button className="text-btn" onClick={onUseModel}>
            Открыть каталог алгоритма
          </button>
          <button className="text-btn" onClick={onOpenRecommendations}>
            Показать подборку модели
          </button>
        </div>
        <p className="demo-disclaimer">
          Цены синтетических курсов условные. Доступ и цены материалов Альфы не
          подтверждены.
        </p>
      </div>
      <section className="demo-commercial" aria-label="Подбор платных предложений">
        <h3>Подбор с учётом цены</h3>
        <p>Сначала учитывается соответствие теме. При включённой прибыли близкие по теме предложения могут поменяться местами. Все суммы и себестоимость — учебные.</p>
        <form className="demo-controls" onSubmit={searchOffers}>
          <label>Что вы хотите изучить?<input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={300} placeholder="Например, маркетинг для бизнеса" /></label>
          <label>Бюджет, ₽<input value={budget} onChange={(event) => setBudget(event.target.value)} type="number" min="1" step="1" placeholder="Без ограничения" /></label>
          <label className="demo-checkbox"><input type="checkbox" checked={preferMargin} onChange={(event) => setPreferMargin(event.target.checked)} /> Учитывать условную прибыль</label>
          <button type="submit" className="primary btn btn--primary" disabled={searching || !draft.trim() || invalidBudget}>{searching ? "Ищем…" : "Подобрать"}</button>
        </form>
        {invalidBudget && <p role="alert">Укажите положительный бюджет в рублях.</p>}
        {submitted && !searching && <>
          <p className="demo-explanation">{modelState} Предложений по теме и бюджету: {ranked.length}. {preferMargin ? "Режим: с учётом условной прибыли." : "Режим: по соответствию теме."}</p>
          {ranked.length ? <div className="results-grid">{ranked.slice(0, 6).map((row, index) => card(row.item, { ...row, position: index + 1 }))}</div> : <p>Платные примеры по этим условиям не найдены. Измените тему или бюджет.</p>}
        </>}
      </section>
      {next && (
        <section className="demo-next">
          <h3>Возможный следующий шаг</h3>
          <p>Пример продолжения темы: вымышленный платный курс.</p>
          {card(next)}
        </section>
      )}
      <div className="demo-controls">
        <label>
          Найти в демо-каталоге
          <input
            value={query}
            onChange={(event) => change(setQuery, event.target.value)}
            placeholder="Например, маркетинг"
          />
        </label>
        <label>
          Источник
          <select
            value={origin}
            onChange={(event) => change(setOrigin, event.target.value)}
          >
            <option value="">Все источники</option>
            <option value="public_snapshot">Снимок Альфы</option>
            <option value="historical_backup">Бэкап</option>
            <option value="synthetic">Вымышленные примеры</option>
          </select>
        </label>
      </div>
      <div className="filterbar" aria-label="Фильтр демо-каталога">
        {TYPES.map(([value, label]) => (
          <button
            type="button"
            key={value}
            className={kind === value ? "selected" : ""}
            aria-pressed={kind === value}
            onClick={() => change(setKind, value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="catalog-count" aria-live="polite">
        Показано {Math.min(shown, matches.length)} из {matches.length} карточек
      </div>
      {matches.length ? (
        <div className="results-grid">
          {matches.slice(0, shown).map((item) => card(item))}
        </div>
      ) : (
        <p>Материалы не найдены. Попробуйте изменить фильтры.</p>
      )}
      {shown < matches.length && (
        <div className="catalog-more">
          <button className="outline" onClick={() => setShown((v) => v + SIZE)}>
            Показать ещё
          </button>
        </div>
      )}
    </section>
  );
}
