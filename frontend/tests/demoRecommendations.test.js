import test from 'node:test';
import assert from 'node:assert/strict';
import {rankDemoOffers} from '../src/features/catalog/demoRecommendations.js';

function offer(id,{price=1000,cost=500,title='Маркетинг для магазина',key=null}={}){
 return {id,title,description:'Практика маркетинга',kind:'course',historical_entity_key:key,
  demo_offer:{price_rub:price,cost_rub:cost,kind:'fictional_simulation'}};
}

test('budget applies to the simulated price and excludes expensive results',()=>{
 const input=[offer('a',{price:1000}),offer('b',{price:2000})];
 assert.deepEqual(rankDemoOffers(input,{query:'маркетинг',maxPrice:1000}).map(x=>x.item.id),['a']);
 assert.throws(()=>rankDemoOffers(input,{query:'маркетинг',maxPrice:0}),/Бюджет/);
});

test('margin reranking moves a similar relevant offer by at most one position',()=>{
 const input=[offer('a',{price:1000,cost:900}),offer('b',{price:2000,cost:500}),
  offer('c',{price:3000,cost:2900}),offer('d',{price:5000,cost:500})];
 const base=rankDemoOffers(input,{query:'маркетинг'});
 const ranked=rankDemoOffers(input,{query:'маркетинг',preferMargin:true});
 assert.deepEqual(base.map(x=>x.item.id),['a','b','c','d']);
 assert.deepEqual(ranked.map(x=>x.item.id),['b','a','d','c']);
 assert.ok(ranked.every((row,index)=>Math.abs(row.originalPosition-(index+1))<=1));
 assert.deepEqual(input.map(x=>x.id),['a','b','c','d']);
});

test('an unrelated expensive product is not introduced by the revenue mode',()=>{
 const input=[offer('a'),offer('b',{title:'Садоводство',price:99999})];input[1].description='Выращивание деревьев';
 assert.deepEqual(rankDemoOffers(input,{query:'маркетинг',preferMargin:true}).map(x=>x.item.id),['a']);
 assert.deepEqual(rankDemoOffers(input,{query:'',preferMargin:true}),[]);
});

test('matching keys can incorporate actual model results',()=>{
 const input=[offer('a',{title:'Управление персоналом',key:'course:real'}),offer('b',{title:'Маркетинг'})];
 input[0].description='Вопросы команды';
 const result=rankDemoOffers(input,{query:'маркетинг',modelResults:[{entity_key:'course:real'}]});
 assert.equal(result.find(x=>x.item.id==='a').matchedModel,true);
 assert.equal(result.find(x=>x.item.id==='b').matchedModel,false);
});

test('matching only by title is explicitly marked unverified',()=>{
 const item=offer('a');item.historical_title_candidate='course:candidate';
 const [result]=rankDemoOffers([item],{query:'маркетинг',modelResults:[{entity_key:'course:candidate'}]});
 assert.equal(result.matchedModel,true);
 assert.equal(result.modelMatch,'title_candidate');
});

test('unmarked or invalid simulated offers never enter recommendations',()=>{
 const input=[offer('a'),offer('b'),offer('c'),offer('d')];
 delete input[1].demo_offer;input[2].demo_offer.kind='known';input[3].demo_offer.cost_rub=2000;
 assert.deepEqual(rankDemoOffers(input,{query:'маркетинг'}).map(x=>x.item.id),['a']);
});

test('marketing does not accidentally match the marketplace prefix',()=>{
 const marketing=offer('marketing',{title:'Интернет-маркетинг'});
 const marketplace=offer('marketplace',{title:'Запуск на маркетплейсах'});
 marketing.description='Продвижение';marketplace.description='Торговая площадка';
 assert.deepEqual(rankDemoOffers([marketing,marketplace],{query:'маркетинг'}).map(x=>x.item.id),['marketing']);
 assert.deepEqual(rankDemoOffers([marketing,marketplace],{query:'маркетплейсы'}).map(x=>x.item.id),['marketplace']);
});

test('generic management wording does not recommend an unrelated subject',()=>{
 const team=offer('team',{title:'Управление командой'});team.description='Постановка задач сотрудникам';
 const finance=offer('finance',{title:'Как управлять финансами'});finance.description='Денежные потоки';
 assert.deepEqual(rankDemoOffers([team,finance],{query:'управление командой',preferMargin:true}).map(x=>x.item.id),['team']);
 assert.deepEqual(rankDemoOffers([team],{query:'управление'}).map(x=>x.item.id),['team']);
});
