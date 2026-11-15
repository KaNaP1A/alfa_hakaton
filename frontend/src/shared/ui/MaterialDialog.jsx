import React from 'react';
import { ArrowUpRight,Check,X } from 'lucide-react';
import { kindLabels } from './MaterialCard.jsx';
export function MaterialDialog({item,completed,onClose,onComplete,onStarted,busy,error}){
 if(!item)return null;
 const verified=item.access_verified===true;
 return <div className="modal-backdrop" onClick={onClose}><div className="modal" role="dialog" aria-modal="true" aria-label="Информация о материале" onClick={e=>e.stopPropagation()}>
 <button className="close-modal" type="button" onClick={onClose} aria-label="Закрыть"><X/></button>
 <span className="section-kicker">{kindLabels[item.kind]||'Материал'}</span><h2>{item.title}</h2><p>{item.description||'Описание отсутствует.'}</p>
 <p className="modal-note">{verified?'Доступ проверен бэкендом по актуальному импортированному каталогу.':'Условия доступа не подтверждены.'}</p>
 {item.price?.status==='known'&&<p><b>Цена:</b> {item.price.amount} {item.price.currency}</p>}
 {item.price?.status!=='known'&&<p className="hint">Стоимость не указана</p>}
 {error&&<p className="notice" role="alert">{error}</p>}
 <div className="modal-actions">
 {verified&&item.canonical_url?.startsWith('https://')&&<a className="primary" href={item.canonical_url} target="_blank" rel="noopener noreferrer" onClick={()=>onStarted(item,'clicked')}>Открыть материал <ArrowUpRight size={16}/></a>}
 {item.kind==='course'&&!completed&&<button className="primary" disabled={busy} onClick={()=>onComplete(item)}>Отметить завершённым <Check size={16}/></button>}
 {completed&&<span className="done"><Check size={16}/> Отмечено как завершённое</span>}
 <button className="outline" onClick={onClose}>Закрыть</button></div><p className="modal-note">Отметка завершения — самоотчёт, а не подтверждённый сертификат.</p>
 </div></div>;
}
