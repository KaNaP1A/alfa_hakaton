import React from "react";
import { ArrowUpRight, Check, X, BookOpen } from "lucide-react";
import { kindLabels } from "./MaterialCard.jsx";
import { CollapsibleText } from "./CollapsibleText.jsx";
import { useDialog } from "./useDialog.js";
export function MaterialDialog({
  item,
  completed,
  onClose,
  onComplete,
  onStarted,
  busy,
  error,
}) {
  const ref = useDialog(onClose);
  if (!item) return null;
  const verified = item.access_verified === true;
  const source = item.source_url?.startsWith("https://kurs.alfabank.ru/");
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="material-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="dialog-top">
          <span className="dialog-type">
            <BookOpen size={17} />
            {kindLabels[item.kind] || "Материал"}
          </span>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="Закрыть материал"
          >
            <X />
          </button>
        </div>
        <h2 id="material-title">{item.title}</h2>
        {item.topics?.length > 0 && (
          <div className="material-topics">
            {item.topics.map((topic) => (
              <span key={topic}>{topic}</span>
            ))}
          </div>
        )}
        <CollapsibleText
          key={item.entity_key}
          text={item.description || "Подробное описание этого материала пока не добавлено."}
          limit={550}
          lines={6}
          className="material-description"
        />
        <div className="material-availability">
          <span>
            {verified ? (
              <>
                <Check size={16} />
                Материал доступен
              </>
            ) : (
              "Условия доступа уточняются"
            )}
          </span>
          {item.price?.status === "known" && (
            <strong>
              {item.price.amount} {item.price.currency || ""}
            </strong>
          )}
          {item.price?.status === "conditional" && (
            <strong>Условная цена: {Number(item.price.amount).toLocaleString("ru-RU")} ₽</strong>
          )}
        </div>
        {error && (
          <p className="notice" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          {verified && item.canonical_url?.startsWith("https://") && (
            <a
              className="primary btn btn--primary"
              href={item.canonical_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => onStarted(item, "clicked")}
            >
              Перейти к материалу
              <ArrowUpRight size={17} />
            </a>
          )}
          {!verified && source && (
            <a
              className="outline btn btn--secondary"
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => onStarted(item, "clicked")}
            >
              Открыть страницу источника <ArrowUpRight size={17} />
            </a>
          )}
          {verified && item.kind === "course" && !completed && (
            <button
              className="outline btn btn--secondary"
              disabled={busy}
              onClick={() => onComplete(item)}
            >
              {busy ? "Сохраняем" : "Отметить изученным"}
              <Check size={17} />
            </button>
          )}
          {completed && (
            <span className="done">
              <Check size={17} />
              Вы отметили этот курс изученным
            </span>
          )}
        </div>
        {!item.canonical_url && (
          <p className="modal-note">
            Ссылка на материал пока не указана в каталоге.
          </p>
        )}
        {item.kind === "course" && (
          <p className="modal-note">
            Отметка сохраняется в вашей истории обучения и не заменяет
            сертификат.
          </p>
        )}
      </div>
    </div>
  );
}
