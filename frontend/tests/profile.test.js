import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanProfile,emptyProfile} from '../src/features/profile/storage.js';
test('clean profile respects FastAPI fields',()=>{const p=cleanProfile({categories:['team'],goal:' Управлять командой '});assert.deepEqual(p.categories,['team']);assert.equal(p.goal,'Управлять командой');assert.equal(p.experience,null);});
test('empty profile has strict allowed fields',()=>{assert.deepEqual(Object.keys(emptyProfile()).sort(),['categories','selected_facets','goal','industry','business_stage','experience','preferred_kinds','region'].sort());});
test('selected topics are normalized, deduplicated and require a category',()=>{
 const p=cleanProfile({categories:['team'],selected_facets:[' Управление  командой ','управление командой','Поиск сотрудников']});
 assert.deepEqual(p.selected_facets,['Управление командой','Поиск сотрудников']);
 assert.deepEqual(cleanProfile({categories:[],selected_facets:['Финансы']}).selected_facets,[]);
});
test('duplicate categories and formats do not produce an invalid profile',()=>{
 const profile=cleanProfile({categories:['team','team'],preferred_kinds:['course','course','webinar']});
 assert.deepEqual(profile.categories,['team']);
 assert.deepEqual(profile.preferred_kinds,['course','webinar']);
});
