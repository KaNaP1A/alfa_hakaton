import React from 'react';
import { GraduationCap, FileText, Headphones, Video, SlidersHorizontal, BookOpen, Sparkles, ArrowUpRight } from 'lucide-react';
export const kindLabels = { course: 'Курс', article: 'Статья', document: 'Документ', webinar: 'Вебинар', podcast: 'Подкаст', calculator: 'Калькулятор' };
const icons = { course: GraduationCap, article: FileText, document: FileText, webinar: Video, podcast: Headphones, calculator: SlidersHorizontal };
export function MaterialCard({ item, onView, viewed }) {
  const Icon = icons[item.kind] || BookOpen;
  return <article className="result-card">
    <div className="item-art" data-kind={item.kind}><div className="art-orbit"/><Icon size={35} strokeWidth={1.5}/><span>АЛЬФА-КУРС</span></div>
    <div className="item-copy">
      <div className="meta"><span className="kind"><Icon size={14}/>{kindLabels[item.kind] || 'Материал'}</span>{item.topics?.[0] && <span className="topic">{item.topics[0]}</span>}</div>
      <h3>{item.title}</h3><p>{item.description || 'Описание не предоставлено.'}</p>
      {(item.reason || item.promotion?.text) && <div className="why"><Sparkles size={15}/><span>{item.reason || item.promotion.text}</span></div>}
      <div className="item-footer"><button type="button" className="text-btn" onClick={() => onView(item)}>{viewed ? 'Просмотрено' : 'Подробнее'} <ArrowUpRight size={16}/></button>{item.price?.status === 'unknown' && <span className="hint">Условия уточняются</span>}</div>
    </div>
  </article>;
}
