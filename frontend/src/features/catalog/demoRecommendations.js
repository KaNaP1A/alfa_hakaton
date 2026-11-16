// This is a fictional commercial demonstration, not a purchase prediction.
const STOP=new Set(['как','что','для','или','это','хочу','мне','могу','нужно','найти','подскажи','пожалуйста','материал','курс','тему','бизнесе','бизнеса','управление','управления','управлению','управлять']);
function words(text,includeManagement=false){
 return [...String(text||'').toLocaleLowerCase('ru').replaceAll('ё','е').matchAll(/[\p{L}\p{N}]+/gu)]
  .map(m=>m[0]).filter(w=>w.length>=3&&(!STOP.has(w)||(includeManagement&&/^(управлен|управля)/.test(w))));
}
function stem(word){
 if(word.startsWith('маркетинг'))return 'маркетинг';
 if(word.startsWith('маркетплейс'))return 'маркетплейс';
 return word.length>6?word.slice(0,6):word;
}
function similarity(item,terms){
 const includeManagement=terms.includes('управл');
 const text=new Set(words(`${item.title} ${item.description||''} ${(item.topics||[]).join(' ')}`,includeManagement).map(stem));
 const title=new Set(words(item.title,includeManagement).map(stem));
 const hits=terms.filter(term=>text.has(term)).length;
 if(!hits)return 0;
 return hits/terms.length + .2*terms.filter(term=>title.has(term)).length/terms.length;
}
function validOffer(offer){
 return offer?.kind==='fictional_simulation' && Number.isInteger(offer.price_rub) && offer.price_rub>0 &&
  Number.isInteger(offer.cost_rub) && offer.cost_rub>=0 && offer.cost_rub<=offer.price_rub;
}
export function rankDemoOffers(items,{query='',maxPrice=null,preferMargin=false,modelResults=[]}={}){
 const terms=[...new Set(words(query).map(stem))];
 if(!terms.length&&/управлен|управля/i.test(query))terms.push('управл');
 if(!terms.length)return [];
 if(maxPrice!==null&&(!Number.isInteger(maxPrice)||maxPrice<=0))throw new Error('Бюджет должен быть положительным целым числом.');
 const modelRanks=new Map();
 modelResults.forEach((result,index)=>{if(result?.entity_key&&!modelRanks.has(result.entity_key))modelRanks.set(result.entity_key,index)});
 const candidates=[];
 for(const item of items){
  const offer=item.demo_offer;
  if(!validOffer(offer)||(maxPrice!==null&&offer.price_rub>maxPrice))continue;
  const textScore=similarity(item,terms);
  const modelKey=item.historical_entity_key||item.historical_title_candidate;
  const rank=modelKey?modelRanks.get(modelKey):undefined;
  if(!textScore&&rank===undefined)continue;
  const relevance=textScore+(rank===undefined?0:.25/(rank+1));
  candidates.push({item,relevance,matchedModel:rank!==undefined,
   modelMatch:rank===undefined?null:item.historical_entity_key?'id':'title_candidate',
   margin:offer.price_rub-offer.cost_rub});
 }
 candidates.sort((a,b)=>b.relevance-a.relevance||a.item.id.localeCompare(b.item.id));
 const ranked=candidates.map((candidate,index)=>({...candidate,originalPosition:index+1}));
 if(preferMargin){
  for(let i=0;i+1<ranked.length;i+=2){
   const a=ranked[i],b=ranked[i+1];
   // A price signal may only swap nearby relevant offers with similar topic match.
   if(a.relevance-b.relevance<=.15&&b.margin>a.margin) [ranked[i],ranked[i+1]]=[b,a];
  }
 }
 return ranked;
}
