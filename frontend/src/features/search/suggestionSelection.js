/**
 * The public backend supports two different suggestion protocols:
 * - demo: search the complete suggested label;
 * - model: keep the user's original q and pass selection_id + generation.
 * The label is always shown in the input and results heading.
 */
export function resolveSuggestion(item, selectionMode, originalQuery) {
  const label = String(item?.label ?? '').trim();
  if (!label) return null;
  const id = item.id;
  const generation = item.selection_generation;
  if (selectionMode === 'selection_id' && id && generation) {
    return { q: originalQuery, options: { selection: { id, generation }, displayQuery: label } };
  }
  return { q: label, options: { displayQuery: label } };
}
