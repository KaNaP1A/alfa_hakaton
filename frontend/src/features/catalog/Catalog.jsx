import React from 'react';
import { Cards, State } from '../../shared/ui/ResultStates.jsx';
import { TYPES } from '../search/SearchResults.jsx';

export function Catalog({state,profile,onOpen,onFilter,onMore,onRetry}) {
  return <>
    <div className="filterbar" aria-label="Фильтр каталога">
      {TYPES.map(([kind,label])=><button type="button" key={kind} className={state.kind===kind?'selected':''} aria-pressed={state.kind===kind} onClick={()=>onFilter(kind)}>{label}</button>)}
    </div>
    {state.error ? <State error={state.error} onRetry={onRetry}/> : state.loading && !state.loaded ?
      <State loading/> : state.loaded && !state.items.length ?
      <State emptyTitle="Пока нет доступных материалов" emptyText="Попробуйте выбрать другой тип материала."/> :
      <>
        <div className="catalog-count" aria-live="polite">Показано {state.items.length} из {state.total} доступных материалов</div>
        <Cards items={state.items} profile={profile} onOpen={onOpen}/>
        {state.items.length<state.total && <div className="catalog-more"><button className="outline" disabled={state.loading} onClick={onMore}>{state.loading?'Загружаем...':'Показать ещё'}</button></div>}
      </>}
  </>;
}
