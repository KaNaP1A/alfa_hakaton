import test from 'node:test';
import assert from 'node:assert/strict';
import { createInterestAutosave } from '../src/features/recommendations/interestAutosave.js';

function fakeClock() {
  const tasks = new Map();
  let id = 0;
  return {
    tasks,
    schedule: fn => { const key = ++id; tasks.set(key, fn); return key; },
    unschedule: key => tasks.delete(key),
    async run() { const entries = [...tasks.values()]; tasks.clear(); for (const fn of entries) await fn(); },
  };
}

test('rapid topic selections are applied automatically as a single latest update', async () => {
  const clock = fakeClock(), calls = [], saved = [];
  const autosave = createInterestAutosave({
    save: async categories => { calls.push(categories); },
    onSaved: categories => saved.push(categories),
    onError: error => { throw error; },
    schedule: clock.schedule, unschedule: clock.unschedule,
  });
  autosave.update(['team']);
  autosave.update(['team', 'marketing']);
  autosave.update(['marketing']);
  assert.equal(calls.length, 0);
  await clock.run();
  assert.deepEqual(calls, [['marketing']]);
  assert.deepEqual(saved, [['marketing']]);
});

test('the next update cannot be overwritten by a slow earlier PUT', async () => {
  const clock = fakeClock(), calls = [], saved = [];
  let finishFirst;
  const first = new Promise(resolve => finishFirst = resolve);
  const autosave = createInterestAutosave({
    save: async categories => {
      calls.push(categories);
      if (calls.length === 1) await first;
    },
    onSaved: categories => saved.push(categories),
    onError: error => { throw error; },
    schedule: clock.schedule, unschedule: clock.unschedule,
  });
  autosave.update(['business']);
  const flushing = clock.run();
  await Promise.resolve();
  autosave.update(['finance']);
  autosave.update(['finance', 'team']);
  finishFirst();
  await flushing;
  await clock.run();
  assert.deepEqual(calls, [['business'], ['finance', 'team']]);
  assert.deepEqual(saved, [['finance', 'team']]);
});

test('errors do not mark the selection saved', async () => {
  const clock = fakeClock(), errors = [], saved = [];
  const autosave = createInterestAutosave({
    save: async () => { throw Error('API недоступен'); },
    onSaved: categories => saved.push(categories),
    onError: error => errors.push(error.message),
    schedule: clock.schedule, unschedule: clock.unschedule,
  });
  autosave.update(['technology']);
  await clock.run();
  assert.deepEqual(saved, []);
  assert.deepEqual(errors, ['API недоступен']);
});

test('reset cancels an unsent request', async () => {
  const clock = fakeClock(), calls = [];
  const autosave = createInterestAutosave({
    save: async categories => calls.push(categories),
    onSaved() {}, onError(error) { throw error; },
    schedule: clock.schedule, unschedule: clock.unschedule,
  });
  autosave.update(['team']);
  autosave.reset();
  await clock.run();
  assert.deepEqual(calls, []);
});
