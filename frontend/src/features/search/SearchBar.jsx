import React,{useState} from 'react';
import { ArrowRight, Search, X } from 'lucide-react';
import { resolveSuggestion } from './suggestionSelection.js';
export function SearchBar({state,onSearch}){
 const [selected,setSelected]=useState(-1);
 const options=[...state.suggestions,...state.relatedTopics];
 function choose(item){
  const selectedSuggestion=resolveSuggestion(item,state.selectionMode,state.query);
  if(!selectedSuggestion)return;
  setSelected(-1);
  state.setSuggestOpen(false);
  onSearch(selectedSuggestion.q,state.kind,selectedSuggestion.options);
 }
 function keyDown(e){if(!state.suggestOpen||!options.length)return;
 if(e.key==='ArrowDown'){e.preventDefault();setSelected(x=>(x+1)%options.length)}
 if(e.key==='ArrowUp'){e.preventDefault();setSelected(x=>(x-1+options.length)%options.length)}
 if(e.key==='Escape'){e.preventDefault();state.setSuggestOpen(false)}
 if(e.key==='Enter'&&selected>=0){e.preventDefault();choose(options[selected])}}
 return <div className="search-area"><form className="search-box" onSubmit={e=>{e.preventDefault();onSearch()}}><Search size={20}/>
 <input aria-label="Поисковый запрос" role="combobox" aria-autocomplete="list" aria-expanded={state.suggestOpen&&options.length>0} aria-controls="search-suggestions" aria-activedescendant={selected>=0?`suggest-${selected}`:undefined} value={state.query} onChange={e=>{state.setQuery(e.target.value);state.setSuggestOpen(true);setSelected(-1)}} onKeyDown={keyDown} onFocus={()=>state.setSuggestOpen(true)} placeholder="Чему хотите научиться?" maxLength={300}/>
 {state.query&&<button className="clear" type="button" aria-label="Очистить" onClick={()=>{state.setQuery('');state.setSuggestOpen(false)}}><X size={18}/></button>}
 <button className="primary" type="submit" aria-label="Найти материалы" disabled={!state.query.trim()}>Найти <ArrowRight size={17}/></button></form>
 {state.suggestOpen&&options.length>0&&<div className="suggest-list" role="listbox" id="search-suggestions">{options.map((s,i)=><button key={`${s.entity_key||s.label}-${i}`} type="button" id={`suggest-${i}`} role="option" aria-selected={selected===i} className={selected===i?'suggest-active':''} onClick={()=>choose(s)}><Search size={15}/><span>{s.label}</span></button>)}</div>}</div>;
}
