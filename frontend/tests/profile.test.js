import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanProfile,emptyProfile} from '../src/features/profile/storage.js';
test('clean profile respects FastAPI fields',()=>{const p=cleanProfile({categories:['team'],goal:' Управлять командой '});assert.deepEqual(p.categories,['team']);assert.equal(p.goal,'Управлять командой');assert.equal(p.experience,null);});
test('empty profile has strict allowed fields',()=>{assert.deepEqual(Object.keys(emptyProfile()).sort(),['categories','goal','industry','business_stage','experience','preferred_kinds','region'].sort());});
