import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {filterDemoItems,orderDemoItems} from '../src/features/catalog/demoCatalog.js';
const {items}=JSON.parse(readFileSync(new URL('../../data/demo_catalog.json',import.meta.url),'utf8'));
test('public and fictional cards retain distinct identifiers',()=>{
 assert.equal(items.filter(x=>x.origin==='public_snapshot').length,1092); assert.equal(items.filter(x=>x.origin==='synthetic').length,12);
 assert.equal(new Set(items.map(x=>x.id)).size,items.length);const ordered=orderDemoItems(items);assert.equal(ordered.length,items.length);assert.equal(ordered[0].origin,'synthetic');assert.equal(ordered[1].origin,'public_snapshot');
});
test('catalog filters source, type and query',()=>{
 const courses=filterDemoItems(items,{kind:'course',origin:'synthetic'});assert.equal(courses.length,6);assert.ok(courses.every(x=>x.price.status==='fictional'));
 const found=filterDemoItems(items,{origin:'public_snapshot',query:'маркетинг'});assert.ok(found.length>0);assert.ok(found.every(x=>x.origin==='public_snapshot'));
});
