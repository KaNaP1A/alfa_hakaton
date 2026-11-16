import React from "react";
import {
  ArrowUpRight,
  Check,
  GraduationCap,
  FileText,
  Headphones,
  Video,
  Calculator,
  BookOpen,
} from "lucide-react";
export const kindLabels = {
  course: "Курс",
  lesson: "Урок",
  article: "Статья",
  document: "Документ",
  webinar: "Вебинар",
  podcast: "Подкаст",
  calculator: "Калькулятор",
};
const icons = {
  course: GraduationCap,
  lesson: BookOpen,
  article: BookOpen,
  document: FileText,
  webinar: Video,
  podcast: Headphones,
  calculator: Calculator,
};
export function MaterialCard({ item, onView, viewed }) {
  const Icon = icons[item.kind] || BookOpen;
  return (
    <article className="result-card card">
      <button
        className="card-open"
        onClick={() => onView(item)}
        aria-label={`Открыть материал «${item.title}»`}
      >
        <div
          className="material-cover"
          data-kind={item.kind}
          aria-hidden="true"
        >
          <span className="cover-kind">
            {kindLabels[item.kind] || "Материал"}
          </span>
          <ArrowUpRight className="cover-arrow" size={22} />
          <div className="cover-object">
            <div className="object-layer layer-back" />
            <div className="object-layer layer-middle" />
            <div className="object-layer layer-front">
              <Icon strokeWidth={1.15} />
            </div>
          </div>
          <span className="cover-topic">
            {item.topics?.[0] || "Знания для бизнеса"}
          </span>
        </div>
        <div className="item-copy">
          <div className="meta">
            <span>{kindLabels[item.kind] || "Материал"}</span>
            {viewed && (
              <span className="viewed-badge">
                <Check size={13} />
                Просмотрено
              </span>
            )}
          </div>
          <h3>{item.title}</h3>
          {item.description && <p>{item.description}</p>}
          {(item.reason || item.promotion?.text) && (
            <div className="why">{item.reason || item.promotion.text}</div>
          )}
          <div className="item-footer">
            <span className="material-action">
              Смотреть материал
              <ArrowUpRight size={16} />
            </span>
            {item.price?.status === "known" && (
              <span className="material-price">
                {item.price.amount} {item.price.currency || ""}
              </span>
            )}
            {item.price?.status === "conditional" && (
              <span className="material-price">
                Условная цена: {Number(item.price.amount).toLocaleString("ru-RU")} ₽
              </span>
            )}
          </div>
        </div>
      </button>
    </article>
  );
}
