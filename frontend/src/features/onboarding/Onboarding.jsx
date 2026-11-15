import React, { useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";
import { useDialog } from "../../shared/ui/useDialog.js";
import { CATEGORIES } from "../profile/storage.js";
const EXAMPLES = [
  "Хочу научиться управлять командой",
  "Хочу разобраться с финансами бизнеса",
  "Хочу продвигать свой продукт",
];
export function Onboarding({ initial, onFinish, onClose }) {
  const dialogRef = useDialog(onClose);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [submitError, setSubmitError] = useState("");
  const [categories, setCategories] = useState(initial.categories);
  const [goal, setGoal] = useState(initial.goal || "");
  function toggle(id) {
    setCategories((old) =>
      old.includes(id) ? old.filter((x) => x !== id) : [...old, id].slice(0, 5),
    );
  }
  async function finish(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setSubmitError("");
    try {
      await onFinish({ categories, goal: goal.trim() || null });
    } catch (error) {
      setSubmitError(error.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="modal-backdrop onboarding-overlay" onClick={onClose}>
      <section
        ref={dialogRef}
        className="onboarding-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="onboarding-top">
          <span className="section-kicker">
            Ваши интересы · шаг {step + 1} из 2
          </span>
          <button
            className="close-modal"
            type="button"
            onClick={onClose}
            aria-label="Закрыть опрос"
          >
            <X />
          </button>
        </div>
        <div className="onboarding-progress">
          <span style={{ width: step === 0 ? "50%" : "100%" }} />
        </div>
        <form onSubmit={finish}>
          {submitError && (
            <p className="notice" role="alert">
              {submitError}
            </p>
          )}
          {step === 0 ? (
            <>
              <h2 id="onboarding-title">Какие темы вам интересны?</h2>
              <p>
                Выберите одну или несколько. По этим направлениям подберём
                первые материалы.
              </p>
              <div className="onboarding-options">
                {CATEGORIES.map(([id, label]) => (
                  <button
                    type="button"
                    key={id}
                    aria-pressed={categories.includes(id)}
                    className={categories.includes(id) ? "selected" : ""}
                    onClick={() => toggle(id)}
                  >
                    {label} {categories.includes(id) && <Check size={17} />}
                  </button>
                ))}
              </div>
              <p className="onboarding-note">
                Можно пропустить выбор: при пустых интересах рекомендации могут
                отсутствовать.
              </p>
              <div className="onboarding-actions">
                <button type="button" className="outline" onClick={onClose}>
                  Не сейчас
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => setStep(1)}
                >
                  Продолжить <ArrowRight size={16} />
                </button>
              </div>
            </>
          ) : (
            <>
              <h2 id="onboarding-title">Чему хотите научиться?</h2>
              <p>
                Опишите конкретную задачу. Сохраните цель, чтобы находить
                материалы по этой задаче.
              </p>
              <label className="onboarding-label" htmlFor="onboarding-goal">
                Ваша цель (необязательно)
              </label>
              <textarea
                id="onboarding-goal"
                maxLength={300}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="Например, хочу научиться управлять командой"
                rows={3}
              />
              <div className="onboarding-examples">
                {EXAMPLES.map((v) => (
                  <button type="button" key={v} onClick={() => setGoal(v)}>
                    {v}
                  </button>
                ))}
              </div>
              <p className="onboarding-note">
                Цель сохранится в профиле. По ней можно будет найти материалы.
              </p>
              <div className="onboarding-actions">
                <button
                  type="button"
                  className="outline"
                  onClick={() => setStep(0)}
                >
                  <ArrowLeft size={16} /> Назад
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  className="primary btn btn--primary"
                >
                  {busy ? "Сохраняем" : "Получить рекомендации"}{" "}
                  <ArrowRight size={16} />
                </button>
              </div>
            </>
          )}
        </form>
      </section>
    </div>
  );
}
