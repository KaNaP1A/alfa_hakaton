'use strict';
const $ = id => document.getElementById(id);
let items = [], kind = 'all', shown = 12, timer;
const labels = {course:'Курс', article:'Статья', document:'Документ', podcast:'Подкаст', webinar:'Вебинар', calculator:'Калькулятор'};
let last = null;
try { last = JSON.parse(localStorage.getItem('demo-last-topic') || 'null'); } catch (_) { last = null; }
function el(tag, className, text) { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = text; return e; }
function card(item) {
  const article = el('article','card'); const top=el('div','card-top');
  top.append(el('span','type',labels[item.kind] || 'Материал'),el('span',`origin${item.origin === 'public_snapshot' ? ' real' : ''}`,item.origin === 'synthetic' ? 'Вымышленный пример' : 'Снимок сайта Альфы'));
  const bottom=el('div','bottom');
  let price='Цена и доступ не проверены';
  if (item.price.status === 'fictional') price=`${item.price.amount.toLocaleString('ru-RU')} ₽ · условная цена`;
  if (item.price.status === 'fictional_free') price='Бесплатно · условный пример';
  bottom.append(el('b','',price));
  if(item.origin === 'synthetic' && item.kind === 'article') {
    const button=el('button','','Изучить пример →'); button.type='button';
    button.addEventListener('click',()=>{last=item.topics[0]; try { localStorage.setItem('demo-last-topic',JSON.stringify(last)); } catch (_) {} renderNext();}); bottom.append(button);
  } else if(item.source_url) {
    const link=el('a','','Источник ↗'); link.href=item.source_url; link.target='_blank'; link.rel='noopener noreferrer'; bottom.append(link);
  }
  article.append(top,el('h3','',item.title),el('p','',item.description || 'Описание отсутствует в снимке.'),bottom); return article;
}
function renderNext(){
  const target=items.find(x=>x.origin==='synthetic'&&x.kind==='course'&&x.topics.includes(last));
  $('next').hidden=!target; $('next-card').replaceChildren(); if(target) $('next-card').append(card(target));
}
function render(){
  const query=$('search').value.trim().toLocaleLowerCase('ru'); const origin=$('origin').value;
  const filtered=items.filter(i=>(kind==='all'||i.kind===kind)&&(origin==='all'||i.origin===origin)&&(!query||`${i.title} ${i.description} ${i.topics.join(' ')}`.toLocaleLowerCase('ru').includes(query)));
  $('count').textContent=filtered.length; $('status').textContent=filtered.length?'':'Материалы не найдены. Попробуйте изменить поиск или фильтр.';
  $('cards').replaceChildren(...filtered.slice(0,shown).map(card)); $('more').hidden=shown>=filtered.length;
}
document.querySelectorAll('.chip').forEach(button=>button.addEventListener('click',()=>{kind=button.dataset.kind;shown=12;document.querySelectorAll('.chip').forEach(b=>b.classList.toggle('active',b===button));render();}));
$('search').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{shown=12;render();},150);});
$('origin').addEventListener('change',()=>{shown=12;render();}); $('more').addEventListener('click',()=>{shown+=12;render();});
fetch('/api/catalog').then(r=>{if(!r.ok)throw Error('Ошибка загрузки');return r.json();}).then(data=>{const synthetic=data.items.filter(x=>x.origin==='synthetic').sort((a,b)=>a.title.localeCompare(b.title,'ru')); const publicItems=data.items.filter(x=>x.origin==='public_snapshot').sort((a,b)=>a.title.localeCompare(b.title,'ru')); items=[]; while(synthetic.length || publicItems.length){ if(synthetic.length) items.push(synthetic.shift()); items.push(...publicItems.splice(0,2)); } renderNext();render();}).catch(()=>{$('status').textContent='Не удалось загрузить каталог. Проверьте, что локальный сервер запущен.';});
