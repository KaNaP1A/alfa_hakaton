import React, { useEffect, useMemo, useState } from "react";
import dataUrl from "../../../../data/demo_catalog.json?url";
import { orderDemoItems, filterDemoItems } from "./demoCatalog.js";
import { kindLabels } from "../../shared/ui/MaterialCard.jsx";
import { TYPES } from "../search/SearchResults.jsx";
import { State } from "../../shared/ui/ResultStates.jsx";

const SIZE = 12;

export function DemoCatalog() {
  const [items, setItems] = useState([]);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [kind, setKind] = useState("");
  const [origin, setOrigin] = useState("");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(SIZE);
  const [lastTopic, setLastTopic] = useState(null);

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

  function change(setValue, value) {
    setValue(value);
    setShown(SIZE);
  }

  function card(item) {
    const synthetic = item.origin === "synthetic";
    const price =
      item.price?.status === "fictional"
        ? `${item.price.amount.toLocaleString("ru-RU")} ₽ · условная цена`
        : item.price?.status === "fictional_free"
          ? "Бесплатно · условный пример"
          : "Цена и доступ не проверены";

    return (
      <article className="result-card demo-card" key={item.id}>
        <div className="item-copy">
          <div className="meta">
            <span className="kind">{kindLabels[item.kind] || "Материал"}</span>
            <span className="topic">
              {synthetic ? "Вымышленный пример" : "Публичный снимок Альфы"}
            </span>
          </div>
          <h3>{item.title}</h3>
          <p>{item.description || "Описание не предоставлено."}</p>
          <div className="item-footer">
            <span className="demo-price">{price}</span>
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
      <p className="notice">
        Демонстрация: материалы из открытого снимка и вымышленные примеры. Цены
        синтетических курсов условные. Доступ и цены материалов Альфы не
        подтверждены. Поиск и рекомендации модели используют отдельный каталог.
      </p>
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
          {matches.slice(0, shown).map(card)}
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
