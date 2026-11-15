import { useEffect, useRef, useState } from 'react';
import { createInterestAutosave } from './interestAutosave.js';

/** Immediate interest selection + serialized server persistence. */
export function useAutoInterests({ profile, saveProfile, refreshRecommendations, generation, active }) {
  const [preview, setPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const current = useRef({});
  current.current = { profile, saveProfile, refreshRecommendations, generation, active };

  const updater = useRef(null);
  if (!updater.current) {
    updater.current = createInterestAutosave({
      save: categories => {
        const state = current.current;
        return state.saveProfile({ ...state.profile, categories });
      },
      onSaved: () => {
        setPreview(null);
        setSaving(false);
        setError('');
        const state = current.current;
        if (state.active) state.refreshRecommendations(state.generation);
      },
      onError: reason => {
        setPreview(null);
        setSaving(false);
        setError(reason?.message || 'Ошибка сети');
        const state = current.current;
        if (state.active) state.refreshRecommendations(state.generation);
      },
    });
  }

  useEffect(() => () => updater.current?.dispose(), []);

  function choose(categories) {
    setPreview([...categories]);
    setSaving(true);
    setError('');
    // The currently displayed list belongs to the previous interests.
    updater.current.update(categories);
  }

  function reset() {
    updater.current.reset();
    setPreview(null);
    setSaving(false);
    setError('');
  }

  return { categories: preview ?? profile.categories, saving, error, choose, reset };
}
