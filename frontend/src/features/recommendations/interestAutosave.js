/**
 * Serializes interest changes so a slower PUT cannot overwrite a newer choice.
 * Several rapid clicks are coalesced into a single request.
 */
export function createInterestAutosave({ save, onSaved, onError, delay = 180, schedule = setTimeout, unschedule = clearTimeout }) {
  let timer = null;
  let pending = null;
  let running = false;
  let version = 0;
  let closed = false;
  let waiters = [];

  async function flush() {
    timer = null;
    if (running || closed || pending === null) return;
    running = true;
    try {
      while (!closed && pending !== null) {
        const categories = pending;
        const requestVersion = version;
        pending = null;
        try {
          await save([...categories]);
          if (!closed && requestVersion === version && pending === null) onSaved([...categories]);
        } catch (error) {
          if (!closed && requestVersion === version && pending === null) onError(error);
        }
      }
    } finally {
      running = false;
      const waiting = waiters;
      waiters = [];
      waiting.forEach(resolve => resolve());
    }
  }

  return {
    update(categories) {
      if (closed) return;
      version++;
      pending = [...categories];
      if (timer !== null) unschedule(timer);
      timer = schedule(flush, delay);
    },
    reset() {
      version++;
      pending = null;
      if (timer !== null) unschedule(timer);
      timer = null;
    },
    waitForIdle() {
      return running ? new Promise(resolve => waiters.push(resolve)) : Promise.resolve();
    },
    dispose() {
      this.reset();
      closed = true;
    },
  };
}
