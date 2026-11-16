export function orderDemoItems(items) {
 const cmp=(a,b)=>a.title.localeCompare(b.title,'ru');
 const synthetic=items.filter(x=>x.origin==='synthetic').sort(cmp);
 const actual=items.filter(x=>x.origin==='public_snapshot').sort(cmp);
 const historical=items.filter(x=>x.origin==='historical_backup').sort(cmp);
 const out=[];
 for(let i=0,j=0,k=0;i<synthetic.length||j<actual.length||k<historical.length;){
  if(i<synthetic.length)out.push(synthetic[i++]);
  if(k<historical.length)out.push(historical[k++]);
  for(let n=0;n<2&&j<actual.length;n++)out.push(actual[j++]);
 }
 return out;
}
export function filterDemoItems(items,{kind='',origin='',query=''}) {
 const q=query.trim().toLocaleLowerCase('ru');
 return items.filter(x=>(!kind||x.kind===kind)&&(!origin||x.origin===origin)&&(!q||`${x.title} ${x.description} ${(x.topics||[]).join(' ')}`.toLocaleLowerCase('ru').includes(q)));
}
