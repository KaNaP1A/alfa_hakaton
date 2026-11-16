import React from 'react';
import {
  ArrowUpRight, BookOpen, FileText, GraduationCap, Headphones,
  SlidersHorizontal, Sparkles, Video,
} from 'lucide-react';

export const kindLabels = {
  course: 'Курс',
  lesson: 'Урок',
  article: 'Статья',
  document: 'Документ',
  webinar: 'Вебинар',
  podcast: 'Подкаст',
  calculator: 'Калькулятор',
};
const icons = {
  course: GraduationCap,
  lesson: BookOpen,
  article: FileText,
  document: FileText,
  webinar: Video,
  podcast: Headphones,
  calculator: SlidersHorizontal,
};

function priceLabel(price) {
  if (price?.status === 'conditional') {
    return `Условная цена: ${Number(price.amount).toLocaleString('ru-RU')} ₽`;
  }
  if (price?.status === 'known') return `${price.amount} ${price.currency}`;
  return 'Условия уточняются';
}

export function MaterialCard({ item, onView, viewed }) {
  const Icon = icons[item.kind] || BookOpen;
  const reason = item.reason || item.promotion?.text;
  return (
    <article className="result-card">
      <div className="item-art" data-kind={item.kind}>
        <div className="art-orbit" />
        <Icon size={35} strokeWidth={1.5} />
        <span>АЛЬФА-КУРС</span>
      </div>
      <div className="item-copy">
        <div className="meta">
          <span className="kind"><Icon size={14} />{kindLabels[item.kind] || 'Материал'}</span>
          {item.topics?.[0] && <span className="topic">{item.topics[0]}</span>}
        </div>
        <h3>{item.title}</h3>
        <p>{item.description || 'Описание не предоставлено.'}</p>
        {reason && <div className="why"><Sparkles size={15} /><span>{reason}</span></div>}
        <div className="item-footer">
          <button type="button" className="text-btn" onClick={() => onView(item)}>
            {viewed ? 'Просмотрено' : 'Подробнее'} <ArrowUpRight size={16} />
          </button>
          <span className="material-price">{priceLabel(item.price)}</span>
        </div>
      </div>
    </article>
  );
}
