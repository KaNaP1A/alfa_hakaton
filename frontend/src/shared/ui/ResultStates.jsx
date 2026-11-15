import React from 'react';
import { AlertCircle, RotateCcw, Search, LoaderCircle } from 'lucide-react';
import { MaterialCard } from './MaterialCard.jsx';
export function State({loading,error,emptyTitle,emptyText,onRetry}){
  if(loading)return <div className="state" role="status"><LoaderCircle size={28} className="spin"/><h3>Подбираем материалы...</h3></div>;
  if(error)return <div className="state" role="alert"><AlertCircle size={27}/><h3>Не удалось получить данные</h3><p>{error}</p>{onRetry&&<button className="outline" onClick={onRetry}><RotateCcw size={15}/>Повторить</button>}</div>;
  return <div className="empty"><Search size={29}/><h3>{emptyTitle}</h3><p>{emptyText}</p></div>;
}
export function Cards({items,profile,onOpen}){return <div className="results-grid">{items.map(item=><MaterialCard key={item.entity_key} item={item} viewed={profile.viewed.includes(item.entity_key)||profile.completed.includes(item.entity_key)} onView={onOpen}/>)}</div>}
