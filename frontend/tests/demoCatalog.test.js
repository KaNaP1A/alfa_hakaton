import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {filterDemoItems,orderDemoItems} from '../src/features/catalog/demoCatalog.js';
const {items}=JSON.parse(readFileSync(new URL('../../data/demo_catalog.json',import.meta.url),'utf8'));
test('public and fictional cards retain distinct identifiers',()=>{
 assert.equal(items.filter(x=>x.origin==='public_snapshot').length,1099); assert.equal(items.filter(x=>x.origin==='synthetic').length,48);
 assert.equal(items.filter(x=>x.origin==='historical_backup').length,10);
 assert.equal(new Set(items.map(x=>x.id)).size,items.length);const ordered=orderDemoItems(items);assert.equal(ordered.length,items.length);assert.equal(ordered[0].origin,'synthetic');assert.equal(ordered[1].origin,'historical_backup');assert.equal(ordered[2].origin,'public_snapshot');
});
test('catalog filters source, type and query',()=>{
 const courses=filterDemoItems(items,{kind:'course',origin:'synthetic'});assert.equal(courses.length,24);assert.ok(courses.every(x=>x.price.status==='fictional'));
 const found=filterDemoItems(items,{origin:'public_snapshot',query:'маркетинг'});assert.ok(found.length>0);assert.ok(found.every(x=>x.origin==='public_snapshot'));
});

test('every free demo article has a paid example in the same topic', () => {
 const synthetic=items.filter(item=>item.origin==='synthetic');
 const articles=synthetic.filter(item=>item.kind==='article');
 const courses=synthetic.filter(item=>item.kind==='course');
 for(const article of articles){
  assert.equal(article.price.status,'fictional_free');
  assert.ok(article.topics.some(topic=>courses.some(course=>
   course.topics.includes(topic)&&course.price.status==='fictional'&&
   Number.isFinite(course.price.amount)&&course.price.amount>0&&course.price.currency==='RUB'
  )),`Missing paid demo course for ${article.id}`);
 }
});

test('fictional prices and source identities remain distinguishable', () => {
 for(const item of items){
  if(item.origin==='synthetic'){
   assert.equal(item.source_url,null);
   assert.ok(['fictional','fictional_free'].includes(item.price.status));
  }else if(item.origin==='public_snapshot'){
   assert.ok(!['fictional','fictional_free'].includes(item.price.status));
   assert.match(item.source_url,/^https:\/\/kurs\.alfabank\.ru\//);
  }
 }
});

test('ordering preserves all recognized cards and does not mutate the input', () => {
 const original=items.map(item=>item.id);
 const ordered=orderDemoItems(items);
 assert.deepEqual(items.map(item=>item.id),original);
 assert.deepEqual(new Set(ordered.map(item=>item.id)),new Set(original));
});

test('text search ignores case and surrounding whitespace', () => {
 const normal=filterDemoItems(items,{origin:'public_snapshot',query:'маркетинг'}).map(item=>item.id);
 const changed=filterDemoItems(items,{origin:'public_snapshot',query:'  МАРКЕТИНГ  '}).map(item=>item.id);
 assert.ok(normal.length>0);
 assert.deepEqual(changed,normal);
 assert.deepEqual(filterDemoItems(items,{query:'zzzz-nonexistent-3948'}),[]);
});

test('priced examples are labeled and do not change unverified public prices', () => {
 const offered=items.filter(item=>item.demo_offer);
 assert.equal(offered.length,225);
 for(const item of offered){
  assert.equal(item.demo_offer.kind,'fictional_simulation');
  assert.ok(item.demo_offer.price_rub>0);
  assert.ok(item.demo_offer.cost_rub>=0&&item.demo_offer.cost_rub<=item.demo_offer.price_rub);
  if(item.origin!=='synthetic')assert.equal(item.price.status,'unknown');
 }
 assert.ok(items.filter(item=>item.kind==='calculator').length>=7);
 assert.ok(items.filter(item=>item.kind==='webinar').length>=9);
 assert.ok(items.filter(item=>item.kind==='lesson').length>=12);
 assert.ok(items.filter(item=>['article','document'].includes(item.kind)).every(item=>!item.demo_offer));
});
