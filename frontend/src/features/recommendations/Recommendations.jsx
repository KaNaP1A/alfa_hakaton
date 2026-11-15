import React from 'react';
import { RotateCcw } from 'lucide-react';
import { CATEGORIES } from '../profile/storage.js';
import { Cards, State } from '../../shared/ui/ResultStates.jsx';
export function Recommendations({state,profile,onOpen,onInterests,onRetry,onOnboarding}) {
  const toggle = id=>onInterests(profile.profile.categories.includes(id)?profile.profile.categories.filter(x=>x!==id):[...profile.profile.categories,id].slice(0,5));
  return <><div className="category-bar"><span className="category-label">Ваши интересы:</span>{CATEGORIES.map(([id,label])=><button key={id} className={profile.profile.categories.includes(id)?'selected':''} aria-pressed={profile.profile.categories.includes(id)} onClick={()=>toggle(id)}>{label}</button>)}<button className="outline" onClick={onRetry}><RotateCcw size={14}/>Применить</button><button className="outline" onClick={onOnboarding}>Изменить анкету</button></div>
    {state.loading||state.error||!state.data?.results?.length?<State loading={state.loading} error={state.error} emptyTitle="Пока нет рекомендаций" emptyText="Выберите интересы и нажмите «Применить»." onRetry={onRetry}/>:<Cards items={state.data.results} profile={profile} onOpen={onOpen}/>}
  </>;
}
