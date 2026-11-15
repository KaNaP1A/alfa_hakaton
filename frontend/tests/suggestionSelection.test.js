import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveSuggestion } from '../src/features/search/suggestionSelection.js';
import { api } from '../src/shared/api/client.js';

test('demo suggestion searches using the full label', async () => {
  const selection=resolveSuggestion({label:'Как открыть ООО',entity_key:'article:demo-ooo'},'replace_query_with_label','как открыть');
  assert.deepEqual(selection,{q:'Как открыть ООО',options:{displayQuery:'Как открыть ООО'}});
  let url;
  globalThis.fetch=async input=>{url=new URL(input,'http://localhost');return {ok:true,status:200,json:async()=>({generation:'demo-v1',results:[]})};};
  await api.search({q:selection.q,...selection.options});
  assert.equal(url.searchParams.get('q'),'Как открыть ООО');
  assert.equal(url.searchParams.has('selection_id'),false);
});

test('model selection keeps original query, sends id and displays full label', async () => {
  const selection=resolveSuggestion({label:'Как открыть ООО',id:'topic-ooo',selection_generation:'g1'},'selection_id','как открыть');
  assert.equal(selection.options.displayQuery,'Как открыть ООО');
  let url;
  globalThis.fetch=async input=>{url=new URL(input,'http://localhost');return {ok:true,status:200,json:async()=>({generation:'g1',results:[]})};};
  await api.search({q:selection.q,selection:selection.options.selection});
  assert.equal(url.searchParams.get('q'),'как открыть');
  assert.equal(url.searchParams.get('selection_id'),'topic-ooo');
  assert.equal(url.searchParams.get('selection_generation'),'g1');
});

test('demo mode ignores selection id even if an id is present',()=>{
  const r=resolveSuggestion({label:'Как открыть ООО',id:'x',selection_generation:'g'},'replace_query_with_label','как открыть');
  assert.equal(r.q,'Как открыть ООО');
  assert.equal(r.options.selection,undefined);
});

test('invalid suggestion is ignored',()=>assert.equal(resolveSuggestion({label:'  '},'selection_id','как'),null));
