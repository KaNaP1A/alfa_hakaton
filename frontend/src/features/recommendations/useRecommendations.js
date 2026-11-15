import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api/index.js";
export function useRecommendations() {
  const [data, setData] = useState(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const active = useRef();
  useEffect(() => () => active.current?.abort(), []);
  function cancel() {
    active.current?.abort();
    setLoading(false);
  }
  async function load(generation) {
    cancel();
    setData(null);
    setError("");
    if (!generation) {
      setError("Каталог ещё не загружен.");
      return;
    }
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    try {
      const result = await api.recommend({ generation }, controller.signal);
      if (!controller.signal.aborted) {
        if (result.generation !== generation)
          throw Error("Каталог обновился. Повторите запрос.");
        setData(result);
      }
    } catch (e) {
      if (!controller.signal.aborted) setError(e.userMessage || e.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return { data, loading, error, load, cancel };
}
