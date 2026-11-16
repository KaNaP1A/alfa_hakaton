import React,{useMemo,useState} from 'react';
import data from '../../../../data/demo_catalog.json';
import {api} from '../../shared/api/index.js';
import {orderDemoItems,filterDemoItems} from './demoCatalog.js';
import {rankDemoOffers} from './demoRecommendations.js';
import {kindLabels} from '../../shared/ui/MaterialCard.jsx';
import {TYPES} from '../search/SearchResults.jsx';

const ITEMS=orderDemoItems(data.items),SIZE=12;
const DEMO_TYPES=TYPES;
const ORIGINS={synthetic:'Вымышленный пример',public_snapshot:'Публичный снимок Альфы',historical_backup:'Снимок бэкапа'};
const money=value=>`${value.toLocaleString('ru-RU')} ₽`;

export function DemoCatalog(){
 const [kind,setKind]=useState(''),[origin,setOrigin]=useState(''),[query,setQuery]=useState(''),[shown,setShown]=useState(SIZE),[lastTopic,setLastTopic]=useState(null);
 const [draft,setDraft]=useState(''),[submitted,setSubmitted]=useState(''),[budget,setBudget]=useState(''),[preferMargin,setPreferMargin]=useState(false);
 const [modelResults,setModelResults]=useState([]),[modelState,setModelState]=useState(''),[loading,setLoading]=useState(false);
 const matches=useMemo(()=>filterDemoItems(ITEMS,{kind,origin,query}),[kind,origin,query]);
 const next=lastTopic&&ITEMS.find(x=>x.origin==='synthetic'&&x.kind==='course'&&x.topics?.includes(lastTopic));
 const budgetValue=budget.trim()===''?null:Number(budget);
 const invalidBudget=budgetValue!==null&&(!Number.isInteger(budgetValue)||budgetValue<=0);
 const ranked=useMemo(()=>submitted&&!invalidBudget?rankDemoOffers(ITEMS,{query:submitted,maxPrice:budgetValue,preferMargin,modelResults}):[],[submitted,budgetValue,invalidBudget,preferMargin,modelResults]);
 function change(set,value){set(value);setShown(SIZE)}
 async function searchOffers(event){
  event.preventDefault();const value=draft.trim();
  if(!value||value.length>300||invalidBudget)return;
  setLoading(true);setModelState('');setModelResults([]);setSubmitted(value);
  try{
   const response=await api.search({q:value,top:50});
   if(response.mode==='http'||response.mode==='python'){
    setModelResults(response.results||[]);
    setModelState('Используется поиск модели; для части курсов связь определена по названию и не подтверждена. Остальные подобраны по словам.');
   }else{
    setModelState('Модель не подключена: показан подбор по словам.');
   }
  }catch{
   setModelState('Поиск модели недоступен: показан подбор по словам.');
  }finally{setLoading(false)}
 }
 function card(item,rank){
  const synthetic=item.origin==='synthetic',offer=item.demo_offer;
  const price=offer?`${money(offer.price_rub)} · условная цена`:item.price?.status==='fictional_free'?'Бесплатно · условный пример':'Цена не указана';
  return <article className="result-card demo-card" key={item.id}><div className="item-copy">
   <div className="meta"><span className="kind">{kindLabels[item.kind]||(item.kind==='lesson'?'Урок':'Материал')}</span><span className="topic">{ORIGINS[item.origin]||'Демо'}</span></div>
   <h3>{item.title}</h3><p>{item.description||'Описание не предоставлено.'}</p>
   {rank&&<p className="demo-reason">{rank.modelMatch==='title_candidate'?'Модель нашла курс с таким названием; связь не подтверждена':rank.matchedModel?'Найдена моделью':'Подобрана по словам запроса'}{` · условная прибыль: ${money(rank.margin)}`}{preferMargin&&rank.originalPosition!==rank.position?` · позиция по теме: ${rank.originalPosition}`:''}</p>}
   <div className="item-footer"><span className="demo-price">{price}{offer&&<> · себестоимость {money(offer.cost_rub)} (условно)</>}</span>
    {synthetic&&item.kind==='article'&&<button type="button" className="text-btn" onClick={()=>setLastTopic(item.topics?.[0])}>Продолжить тему →</button>}
    {!synthetic&&item.source_url&&<a className="text-btn" href={item.source_url} target="_blank" rel="noreferrer">Источник ↗</a>}
   </div>
   {offer?.reference&&<small className="demo-price">Ориентир — цена из снимка; совпадение и актуальность не подтверждены.</small>}
  </div></article>;
 }
 return <section aria-label="Демонстрационный каталог">
  <p className="notice">Демонстрация: цены и себестоимость ниже условные, реальные предложения и доступ не подтверждены. Статьи и документы не тарифицируются.</p>
  <section className="demo-commercial" aria-label="Подбор платных предложений">
   <h3>Подбор с учётом цены</h3>
   <p>Сначала учитывается соответствие теме. При включённой прибыли близкие по теме предложения могут поменяться местами. Все суммы и себестоимость — учебные.</p>
   <form className="demo-controls" onSubmit={searchOffers}>
    <label>Что вы хотите изучить?<input value={draft} onChange={e=>setDraft(e.target.value)} maxLength={300} placeholder="Например, маркетинг для бизнеса"/></label>
    <label>Бюджет, ₽ <input value={budget} onChange={e=>setBudget(e.target.value)} type="number" min="1" step="1" placeholder="Без ограничения"/></label>
    <label className="demo-checkbox"><input type="checkbox" checked={preferMargin} onChange={e=>setPreferMargin(e.target.checked)}/> Учитывать условную прибыль</label>
    <button type="submit" className="primary" disabled={loading||!draft.trim()||invalidBudget}>{loading?'Ищем…':'Подобрать'}</button>
   </form>
   {invalidBudget&&<p role="alert">Укажите положительный бюджет в рублях.</p>}
   {submitted&&!loading&&<><p className="demo-explanation">{modelState} Предложений по теме и бюджету: {ranked.length}. {preferMargin?'Режим: с учётом условной прибыли.':'Режим: по соответствию теме.'}</p>
    {ranked.length?<div className="results-grid">{ranked.slice(0,6).map((row,index)=>card(row.item,{...row,position:index+1}))}</div>:<p>Платные примеры по этим условиям не найдены. Измените тему или бюджет.</p>}</>}
  </section>
  {next&&<section className="demo-next"><h3>Возможный следующий шаг</h3><p>Пример продолжения темы: вымышленный платный курс.</p>{card(next)}</section>}
  <div className="demo-controls"><label>Найти в демо-каталоге <input value={query} onChange={e=>change(setQuery,e.target.value)} placeholder="Например, маркетинг"/></label><label>Источник <select value={origin} onChange={e=>change(setOrigin,e.target.value)}><option value="">Все источники</option><option value="public_snapshot">Снимок Альфы</option><option value="historical_backup">Бэкап</option><option value="synthetic">Вымышленные примеры</option></select></label></div>
  <div className="filterbar" aria-label="Фильтр демо-каталога">{DEMO_TYPES.map(([value,label])=><button type="button" key={value} className={kind===value?'selected':''} aria-pressed={kind===value} onClick={()=>change(setKind,value)}>{label}</button>)}</div>
  <div className="catalog-count" aria-live="polite">Показано {Math.min(shown,matches.length)} из {matches.length} карточек</div>{matches.length?<div className="results-grid">{matches.slice(0,shown).map(item=>card(item))}</div>:<p>Материалы не найдены. Попробуйте изменить фильтры.</p>}{shown<matches.length&&<div className="catalog-more"><button className="outline" onClick={()=>setShown(v=>v+SIZE)}>Показать ещё</button></div>}
 </section>;
}
