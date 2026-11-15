import React, { useState, useEffect, useRef } from "react";
import { ArrowRight, Search, X } from "lucide-react";
export function SearchBar({ state, onSearch }) {
  const wrapper = useRef(null);
  const [selected, setSelected] = useState(-1);
  const options = [...state.suggestions, ...state.relatedTopics];
  useEffect(() => {
    setSelected(-1);
  }, [state.suggestions, state.relatedTopics]);
  useEffect(() => {
    const outside = (event) => {
      if (!wrapper.current?.contains(event.target)) state.setSuggestOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [state.setSuggestOpen]);
  function choose(item) {
    if (!item) return;
    setSelected(-1);
    if (item.id && item.selection_generation)
      onSearch(state.query, state.kind, {
        selection: { id: item.id, generation: item.selection_generation },
      });
    else onSearch(item.label, state.kind);
  }
  function keyDown(e) {
    if (!state.suggestOpen || !options.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((x) => (x + 1) % options.length);
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((x) =>
        x < 0 ? options.length - 1 : (x - 1 + options.length) % options.length,
      );
    }
    if (e.key === "Escape") {
      e.preventDefault();
      state.setSuggestOpen(false);
    }
    if (e.key === "Enter" && selected >= 0) {
      e.preventDefault();
      choose(options[selected]);
    }
  }
  return (
    <div className="search-area" ref={wrapper}>
      <label className="search-label" htmlFor="knowledge-search">
        Задача или тема обучения
      </label>
      <form
        className="search-box"
        onSubmit={(e) => {
          e.preventDefault();
          onSearch();
        }}
      >
        <Search size={20} />
        <input
          id="knowledge-search"
          aria-label="Поисковый запрос"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={state.suggestOpen && options.length > 0}
          aria-controls={
            state.suggestOpen && options.length
              ? "search-suggestions"
              : undefined
          }
          aria-activedescendant={
            selected >= 0 && selected < options.length
              ? `suggest-${selected}`
              : undefined
          }
          value={state.query}
          onChange={(e) => {
            state.setQuery(e.target.value);
            state.setSuggestOpen(true);
            setSelected(-1);
          }}
          onKeyDown={keyDown}
          onFocus={() => state.setSuggestOpen(true)}
          placeholder="Какую задачу вы хотите решить?"
          maxLength={300}
        />
        {state.query && (
          <button
            className="clear"
            type="button"
            aria-label="Очистить"
            onClick={() => {
              state.setQuery("");
              state.setSuggestOpen(false);
            }}
          >
            <X size={18} />
          </button>
        )}
        <button
          className="primary btn btn--primary"
          type="submit"
          disabled={!state.query.trim()}
        >
          Найти материалы <ArrowRight size={17} />
        </button>
      </form>
      {state.suggestOpen && options.length > 0 && (
        <div className="suggest-list" role="listbox" id="search-suggestions">
          {options.map((s, i) => (
            <button
              key={`${s.entity_key || s.label}-${i}`}
              type="button"
              id={`suggest-${i}`}
              role="option"
              aria-selected={selected === i}
              className={selected === i ? "suggest-active" : ""}
              onClick={() => choose(s)}
            >
              <Search size={15} />
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
