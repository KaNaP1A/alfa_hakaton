import React from "react";
import { ArrowUpRight, Compass, Lightbulb, RotateCcw } from "lucide-react";
import { State } from "../../shared/ui/ResultStates.jsx";
export function LearningPlan({ state, onOpen, onRetry }) {
  if (state.loading || state.error)
    return (
      <State loading={state.loading} error={state.error} onRetry={onRetry} />
    );
  return (
    <div className="plan-layout">
      {state.data?.steps?.length ? (
        <div className="steps">
          {state.data.steps.map((step, i) => (
            <div
              className="step"
              key={`${step.material?.entity_key || i}-${i}`}
            >
              <span className="step-num">{step.number || i + 1}</span>
              <div>
                <span className="step-label">Шаг {step.number || i + 1}</span>
                <h3>{step.material?.title || "Учебный материал"}</h3>
                <p>{step.why}</p>
                {step.material && (
                  <button
                    className="step-link"
                    onClick={() => onOpen(step.material)}
                  >
                    Открыть материал <ArrowUpRight size={15} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">
          <Compass size={30} />
          <h3>
            {state.data?.status === "needs_activity"
              ? "Нужна история просмотра"
              : "Пока недостаточно данных"}
          </h3>
          <p>
            {state.data?.notice ||
              "Посмотрите материалы, затем обновите маршрут."}
          </p>
        </div>
      )}
      <aside className="info-aside">
        <Lightbulb size={23} />
        <b>Как работает маршрут</b>
        <p>
          Посмотрите материалы по интересующей теме — они помогут выбрать
          следующие шаги.
        </p>
        {state.data?.notice && (
          <p className="field-help">
            Маршрут составлен по вашей истории просмотра.
          </p>
        )}
        <button className="outline" onClick={onRetry}>
          <RotateCcw size={15} />
          Обновить маршрут
        </button>
      </aside>
    </div>
  );
}
