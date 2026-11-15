import React from 'react';
import { CATEGORIES } from '../profile/storage.js';
import { Cards, State } from '../../shared/ui/ResultStates.jsx';

export function Recommendations({
  state, profile, onOpen, selectedCategories, onInterests, savingInterests, interestsError, onRetry,
}) {
  function toggle(id) {
    const next = selectedCategories.includes(id)
      ? selectedCategories.filter(category => category !== id)
      : [...selectedCategories, id];
    onInterests(next);
  }

  return <>
    <div className="category-bar" role="group" aria-label="Интересующие темы">
      <span className="category-label">Ваши интересы:</span>
      {CATEGORIES.map(([id, label]) => <button
        type="button"
        key={id}
        className={selectedCategories.includes(id) ? 'selected' : ''}
        aria-pressed={selectedCategories.includes(id)}
        onClick={() => toggle(id)}
      >{label}</button>)}
    </div>
    <p className="interest-status" role="status" aria-live="polite">
      {savingInterests ? 'Обновляем подборку…' : 'Выберите темы — рекомендации обновятся автоматически.'}
    </p>
    {interestsError && <p className="notice" role="alert">Не удалось сохранить интересы: {interestsError}. Попробуйте выбрать тему снова.</p>}
    {savingInterests
      ? <State loading emptyTitle="" emptyText="" />
      : state.loading || state.error || !state.data?.results?.length
        ? <State
          loading={state.loading}
          error={state.error}
          emptyTitle="Пока нет рекомендаций"
          emptyText="Выберите интересующие темы. Если подходящих материалов нет, попробуйте другие направления."
          onRetry={onRetry}
        />
        : <Cards items={state.data.results} profile={profile} onOpen={onOpen} />}
  </>;
}
