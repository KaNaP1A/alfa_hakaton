import React,{useMemo,useState} from 'react';
import data from '../../../../data/demo_catalog.json';
import {orderDemoItems,filterDemoItems} from './demoCatalog.js';
import {kindLabels} from '../../shared/ui/MaterialCard.jsx';
import {TYPES} from '../search/SearchResults.jsx';
const ITEMS=orderDemoItems(data.items),SIZE=12;
export function DemoCatalog(){
 const [kind,setKind]=useState(''),[origin,setOrigin]=useState(''),[query,setQuery]=useState(''),[shown,setShown]=useState(SIZE),[lastTopic,setLastTopic]=useState(null);
 const matches=useMemo(()=>filterDemoItems(ITEMS,{kind,origin,query}),[kind,origin,query]);
 const next=lastTopic&&ITEMS.find(x=>x.origin==='synthetic'&&x.kind==='course'&&x.topics?.includes(lastTopic));
 function change(set,value){set(value);setShown(SIZE)}
 function card(item){
  const synthetic=item.origin==='synthetic';
  const price=item.price?.status==='fictional'?`${item.price.amount.toLocaleString('ru-RU')} ₽ · условная цена`:item.price?.status==='fictional_free'?'Бесплатно · условный пример':'Цена и доступ не проверены';
  return <article className="result-card demo-card" key={item.id}><div className="item-copy"><div className="meta"><span className="kind">{kindLabels[item.kind]||'Материал'}</span><span className="topic">{synthetic?'Вымышленный пример':'Публичный снимок Альфы'}</span></div><h3>{item.title}</h3><p>{item.description||'Описание не предоставлено.'}</p><div className="item-footer"><span className="demo-price">{price}</span>{synthetic&&item.kind==='article'&&<button className="text-btn" onClick={()=>setLastTopic(item.topics?.[0])}>Продолжить тему →</button>}{!synthetic&&item.source_url&&<a className="text-btn" href={item.source_url} target="_blank" rel="noreferrer">Источник ↗</a>}</div></div></article>;
 }
 return <section aria-label="Демонстрационный каталог"><p className="notice">Демонстрация: материалы из открытого снимка и вымышленные примеры. Цены синтетических курсов условные. Доступ и цены материалов Альфы не подтверждены. Поиск и рекомендации модели используют отдельный каталог.</p>
 {next&&<section className="demo-next"><h3>Возможный следующий шаг</h3><p>Пример продолжения темы: вымышленный платный курс.</p>{card(next)}</section>}
 <div className="demo-controls"><label>Найти в демо-каталоге <input value={query} onChange={e=>change(setQuery,e.target.value)} placeholder="Например, маркетинг"/></label><label>Источник <select value={origin} onChange={e=>change(setOrigin,e.target.value)}><option value="">Все источники</option><option value="public_snapshot">Снимок Альфы</option><option value="synthetic">Вымышленные примеры</option></select></label></div>
 <div className="filterbar" aria-label="Фильтр демо-каталога">{TYPES.map(([value,label])=><button type="button" key={value} className={kind===value?'selected':''} aria-pressed={kind===value} onClick={()=>change(setKind,value)}>{label}</button>)}</div>
 <div className="catalog-count" aria-live="polite">Показано {Math.min(shown,matches.length)} из {matches.length} карточек</div>{matches.length?<div className="results-grid">{matches.slice(0,shown).map(card)}</div>:<p>Материалы не найдены. Попробуйте изменить фильтры.</p>}{shown<matches.length&&<div className="catalog-more"><button className="outline" onClick={()=>setShown(v=>v+SIZE)}>Показать ещё</button></div>}</section>;
}
