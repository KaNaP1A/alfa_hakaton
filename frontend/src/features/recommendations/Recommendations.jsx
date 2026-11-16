import React,{useEffect,useState} from 'react';
import { RotateCcw } from 'lucide-react';
import { api } from '../../shared/api/index.js';
import { CATEGORIES } from '../profile/storage.js';
import { Cards, State } from '../../shared/ui/ResultStates.jsx';

export function Recommendations({generation,state,profile,onOpen,onInterests,onFacets,onRetry,onOnboarding}) {
  const [directory,setDirectory]=useState([]),[loadingTopics,setLoadingTopics]=useState(false),[topicError,setTopicError]=useState(''),[saving,setSaving]=useState(false);
  useEffect(()=>{
    if(!generation)return;
    const controller=new AbortController();setLoadingTopics(true);setTopicError('');
    api.interests(controller.signal).then(result=>{
      if(!controller.signal.aborted){
        if(result.generation!==generation)throw Error('Каталог обновился. Обновите страницу.');
        setDirectory(result.categories||[]);
      }
    }).catch(error=>{if(!controller.signal.aborted)setTopicError(error.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoadingTopics(false)});
    return()=>controller.abort();
  },[generation]);
  const selected=profile.profile.categories;
  const selectedFacets=profile.profile.selected_facets||[];
  const topics=[...new Map(directory.filter(c=>selected.includes(c.id)).flatMap(c=>c.topics||[]).map(t=>[t.value.toLocaleLowerCase('ru'),t])).values()];
  async function change(action){setSaving(true);try{await action()}finally{setSaving(false)}}
  function toggle(id){const next=selected.includes(id)?selected.filter(x=>x!==id):[...selected,id].slice(0,5);return change(()=>onInterests(next))}
  function toggleFacet(value){const next=selectedFacets.includes(value)?selectedFacets.filter(x=>x!==value):[...selectedFacets,value].slice(0,20);return change(()=>onFacets(next))}
  return <>
    <div className="category-bar"><span className="category-label">Ваши интересы:</span>{CATEGORIES.map(([id,label])=><button key={id} disabled={saving} className={selected.includes(id)?'selected':''} aria-pressed={selected.includes(id)} onClick={()=>toggle(id)}>{label}</button>)}<button className="outline" disabled={saving} onClick={onRetry}><RotateCcw size={14}/>Применить</button><button className="outline" onClick={onOnboarding}>Изменить анкету</button></div>
    {selected.length>0&&<div className="category-bar" aria-label="Темы интересов"><span className="category-label">Темы:</span>{loadingTopics?<span>Загружаем темы…</span>:topics.map(topic=><button key={topic.value} disabled={saving} className={selectedFacets.includes(topic.value)?'selected':''} aria-pressed={selectedFacets.includes(topic.value)} onClick={()=>toggleFacet(topic.value)}>{topic.label}</button>)}{!loadingTopics&&!topics.length&&!topicError&&<span>Для этих направлений темы пока не найдены.</span>}</div>}
    {topicError&&<p className="notice" role="alert">Не удалось загрузить темы: {topicError}</p>}
    {state.loading||state.error||!state.data?.results?.length?<State loading={state.loading} error={state.error} emptyTitle="Пока нет рекомендаций" emptyText="Выберите интересы и нажмите «Применить»." onRetry={onRetry}/>:<Cards items={state.data.results} profile={profile} onOpen={onOpen}/>}
  </>;
}
