import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api/index.js";
const aborted = (e) => e?.name === "AbortError";
export function useSearch(generation, onGenerationChanged) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [relatedTopics, setRelatedTopics] = useState([]);
  const active = useRef();
  const suggestionController = useRef();
  useEffect(() => {
    suggestionController.current?.abort();
    if (!query.trim() || query.length > 300) {
      setSuggestions([]);
      setRelatedTopics([]);
      return;
    }
    const controller = new AbortController();
    suggestionController.current = controller;
    const timer = setTimeout(async () => {
      try {
        const data = await api.suggest(query, controller.signal);
        if (
          !controller.signal.aborted &&
          (!generation || data.generation === generation)
        ) {
          setSuggestions(data.completions || []);
          setRelatedTopics(data.related_topics || []);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setSuggestions([]);
          setRelatedTopics([]);
        }
      }
    }, 220);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, generation]);
  useEffect(
    () => () => {
      active.current?.abort();
      suggestionController.current?.abort();
    },
    [],
  );
  function cancel() {
    active.current?.abort();
    setLoading(false);
  }
  function reset() {
    cancel();
    setSubmitted("");
    setResult(null);
    setError("");
    setKind("");
  }
  async function search(q = query, k = kind, options = {}) {
    if (!q.trim()) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setSubmitted(q);
    setQuery(q);
    setKind(k);
    setSuggestOpen(false);
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await api.search({
        q,
        kind: k,
        ...options,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (generation && data.generation !== generation) {
        onGenerationChanged(data.generation);
        setError("Каталог обновился. Повторите поиск.");
        return;
      }
      setResult(data);
    } catch (e) {
      if (!aborted(e) && !controller.signal.aborted)
        setError(e.userMessage || e.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return {
    query,
    setQuery,
    kind,
    setKind,
    submitted,
    result,
    loading,
    error,
    suggestions,
    relatedTopics,
    suggestOpen,
    setSuggestOpen,
    search,
    cancel,
    reset,
  };
}
