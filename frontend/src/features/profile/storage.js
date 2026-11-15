export const CATEGORIES = [
  ['business','Бизнес'],['finance','Финансы'],['team','Команда'],
  ['marketing','Маркетинг'],['technology','Технологии'],
];
export const emptyProfile = () => ({categories:[],goal:null,industry:null,business_stage:null,experience:null,preferred_kinds:[],region:null});
export function cleanProfile(data={}) {
  const source={...emptyProfile(),...data};
  return {
    categories:Array.isArray(source.categories)?source.categories.filter(x=>CATEGORIES.some(([id])=>id===x)).slice(0,5):[],
    goal:source.goal?.trim()?.slice(0,300)||null,
    industry:source.industry?.trim()?.slice(0,150)||null,
    business_stage:source.business_stage?.trim()?.slice(0,50)||null,
    experience:source.experience?.trim()?.slice(0,50)||null,
    preferred_kinds:Array.isArray(source.preferred_kinds)?source.preferred_kinds.slice(0,6):[],
    region:source.region?.trim()?.slice(0,150)||null,
  };
}
