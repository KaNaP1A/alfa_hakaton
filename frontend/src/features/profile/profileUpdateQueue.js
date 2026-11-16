/** Serialize complete profile writes so slower requests cannot replace newer changes. */
export function createProfileUpdateQueue() {
  let pending = Promise.resolve();
  return {
    run(task) {
      const result = pending.then(task);
      pending = result.catch(() => {});
      return result;
    },
    waitForIdle() {
      return pending;
    },
  };
}
