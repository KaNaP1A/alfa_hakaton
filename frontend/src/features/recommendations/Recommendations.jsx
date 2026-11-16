import React, { useEffect, useState } from 'react';
import { api } from '../../shared/api/index.js';
import { CATEGORIES } from '../profile/storage.js';
import { Cards, State } from '../../shared/ui/ResultStates.jsx';

export function Recommendations({
  generation, state, profile, onOpen, selectedCategories, onInterests, onFacets,
  savingInterests, interestsError, onRetry, onOnboarding,
}) {
  const [directory, setDirectory] = useState([]);
  const [loadingTopics, setLoadingTopics] = useState(false);
  const [topicError, setTopicError] = useState('');
  const [savingFacets, setSavingFacets] = useState(false);
  useEffect(() => {
    if (!generation) return;
    const controller = new AbortController();
    setLoadingTopics(true); setTopicError('');
    api.interests(controller.signal).then(result => {
      if (!controller.signal.aborted) {
        if (result.generation !== generation) throw Error('Каталог обновился. Обновите страницу.');
        setDirectory(result.categories || []);
      }
    }).catch(error => { if (!controller.signal.aborted) setTopicError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoadingTopics(false); });
    return () => controller.abort();
  }, [generation]);
  const selectedFacets = profile.profile.selected_facets || [];
  const topics = [...new Map(directory.filter(category => selectedCategories.includes(category.id))
    .flatMap(category => category.topics || [])
    .map(topic => [topic.value.toLocaleLowerCase('ru'), topic])).values()];
  function toggle(id) {
    const next = selectedCategories.includes(id)
      ? selectedCategories.filter(category => category !== id)
      : [...selectedCategories, id];
    onInterests(next);
  }
  async function toggleFacet(value) {
    const next = selectedFacets.includes(value)
      ? selectedFacets.filter(facet => facet !== value)
      : [...selectedFacets, value].slice(0, 20);
    setSavingFacets(true);
    try { await onFacets(next); } catch {} finally { setSavingFacets(false); }
  }

  return <>
    <div className="category-bar" role="group" aria-label="Интересующие темы">
      <span className="category-label">Ваши интересы:</span>
      {CATEGORIES.map(([id, label]) => <button
        type="button"
        key={id}
        disabled={savingFacets}
        className={selectedCategories.includes(id) ? 'selected' : ''}
        aria-pressed={selectedCategories.includes(id)}
        onClick={() => toggle(id)}
      >{label}</button>)}
      <button type="button" className="outline" onClick={onOnboarding}>Изменить анкету</button>
    </div>
    {selectedCategories.length > 0 && <div className="category-bar" role="group" aria-label="Темы интересов">
      <span className="category-label">Темы:</span>
      {loadingTopics ? <span>Загружаем темы…</span> : topics.map(topic => <button
        type="button" key={topic.value} disabled={savingInterests || savingFacets}
        className={selectedFacets.includes(topic.value) ? 'selected' : ''}
        aria-pressed={selectedFacets.includes(topic.value)}
        onClick={() => toggleFacet(topic.value)}
      >{topic.label}</button>)}
      {!loadingTopics && !topics.length && !topicError && <span>Для этих направлений темы пока не найдены.</span>}
    </div>}
    {topicError && <p className="notice" role="alert">Не удалось загрузить темы: {topicError}</p>}
    <p className="interest-status" role="status" aria-live="polite">
      {savingInterests || savingFacets ? 'Обновляем подборку…' : 'Выберите темы — рекомендации обновятся автоматически.'}
    </p>
    {interestsError && <p className="notice" role="alert">Не удалось сохранить интересы: {interestsError}. Попробуйте выбрать тему снова.</p>}
    {savingInterests || savingFacets
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
