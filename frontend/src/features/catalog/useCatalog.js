import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api/index.js";

// Catalog is the source of the initial feed. Search and recommendations remain separate.
const PAGE_SIZE = 12;
export function useCatalog() {
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const requestRef = useRef(null);
  const versionRef = useRef(0);
  useEffect(() => () => requestRef.current?.abort(), []);
  function cancel() {
    versionRef.current += 1;
    requestRef.current?.abort();
    setLoading(false);
  }
  async function load(generation, nextKind = "", append = false) {
    cancel();
    if (!append) {
      setItems([]);
      setTotal(0);
      setLoaded(false);
    }
    setKind(nextKind);
    setError("");
    if (!generation) {
      setError("Каталог ещё не загружен.");
      return;
    }
    const controller = new AbortController();
    requestRef.current = controller;
    const version = versionRef.current;
    setLoading(true);
    try {
      const data = await api.catalog(
        { kind: nextKind, limit: PAGE_SIZE, offset: append ? items.length : 0 },
        controller.signal,
      );
      if (controller.signal.aborted || version !== versionRef.current) return;
      if (data.generation !== generation)
        throw Error("Каталог обновился. Перезагрузите страницу.");
      setItems((old) =>
        append ? [...old, ...(data.items || [])] : data.items || [],
      );
      setTotal(data.total || 0);
      setLoaded(true);
    } catch (e) {
      if (!controller.signal.aborted && version === versionRef.current)
        setError(e.userMessage || e.message);
    } finally {
      if (!controller.signal.aborted && version === versionRef.current)
        setLoading(false);
    }
  }
  function clear() {
    cancel();
    setItems([]);
    setTotal(0);
    setKind("");
    setError("");
    setLoaded(false);
  }
  return { items, total, kind, loading, error, loaded, load, cancel, clear };
}
