import test from 'node:test';
import assert from 'node:assert/strict';
import { createProfileUpdateQueue } from '../src/features/profile/profileUpdateQueue.js';

test('profile writes finish in order and a failed write does not stop later saves', async () => {
  const queue = createProfileUpdateQueue();
  let finishFirst;
  const first = new Promise(resolve => { finishFirst = resolve; });
  const seen = [];
  const old = queue.run(async () => { await first; seen.push('old'); });
  const failed = queue.run(async () => { seen.push('failed'); throw Error('network'); });
  const latest = queue.run(async () => { seen.push('latest'); });
  await Promise.resolve();
  assert.deepEqual(seen, []);
  finishFirst();
  await old;
  await assert.rejects(failed, /network/);
  await latest;
  await queue.waitForIdle();
  assert.deepEqual(seen, ['old', 'failed', 'latest']);
});
