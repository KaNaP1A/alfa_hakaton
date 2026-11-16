export const CATEGORIES = [
  ['business', 'Бизнес'],
  ['finance', 'Финансы'],
  ['team', 'Команда'],
  ['marketing', 'Маркетинг'],
  ['technology', 'Технологии'],
];

export const emptyProfile = () => ({
  categories: [],
  selected_facets: [],
  goal: null,
  industry: null,
  business_stage: null,
  experience: null,
  preferred_kinds: [],
  region: null,
});

export function cleanProfile(data = {}) {
  const source = { ...emptyProfile(), ...data };
  const categories = Array.isArray(source.categories)
    ? [...new Set(source.categories.filter(value => CATEGORIES.some(([id]) => id === value)))].slice(0, 5)
    : [];
  const seen = new Set();
  const facets = Array.isArray(source.selected_facets)
    ? source.selected_facets
        .filter(value => typeof value === 'string' && value.trim())
        .map(value => value.trim().replace(/\s+/g, ' ').slice(0, 150))
        .filter(value => {
          const key = value.toLocaleLowerCase('ru');
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
        .slice(0, 20)
    : [];

  return {
    categories,
    selected_facets: categories.length ? facets : [],
    goal: source.goal?.trim()?.slice(0, 300) || null,
    industry: source.industry?.trim()?.slice(0, 150) || null,
    business_stage: source.business_stage?.trim()?.slice(0, 50) || null,
    experience: source.experience?.trim()?.slice(0, 50) || null,
    preferred_kinds: Array.isArray(source.preferred_kinds)
      ? [...new Set(source.preferred_kinds)].slice(0, 7)
      : [],
    region: source.region?.trim()?.slice(0, 150) || null,
  };
}
