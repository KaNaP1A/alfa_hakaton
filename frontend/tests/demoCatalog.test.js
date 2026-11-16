import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {items}=JSON.parse(readFileSync(new URL('../../data/demo_catalog.json',import.meta.url),'utf8'));
test('public and fictional cards retain distinct identifiers',()=>{
 assert.equal(items.filter(x=>x.origin==='public_snapshot').length,1099); assert.equal(items.filter(x=>x.origin==='synthetic').length,48);
 assert.equal(items.filter(x=>x.origin==='historical_backup').length,10);
 assert.equal(new Set(items.map(x=>x.id)).size,items.length);
});
test('synthetic course fixtures have explicitly fictional prices',()=>{
 const courses=items.filter(x=>x.kind==='course'&&x.origin==='synthetic');assert.equal(courses.length,24);assert.ok(courses.every(x=>x.price.status==='fictional'));
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
