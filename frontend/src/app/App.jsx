import React,{useEffect,useState} from 'react';
import { createPortal } from 'react-dom';
import { ArrowRight,ArrowUpRight,BookOpen,Check,Compass,Menu,Search,Sparkles,Target,X } from 'lucide-react';
import { api } from '../shared/api/index.js';
import { useAuth } from '../features/auth/useAuth.js';
import { AuthScreen } from '../features/auth/AuthScreen.jsx';
import { useProfile } from '../features/profile/useProfile.js';
import { useSearch } from '../features/search/useSearch.js';
import { SearchBar } from '../features/search/SearchBar.jsx';
import { SearchResults } from '../features/search/SearchResults.jsx';
import { useCatalog } from '../features/catalog/useCatalog.js';
import { Catalog } from '../features/catalog/Catalog.jsx';
import { DemoCatalog } from '../features/catalog/DemoCatalog.jsx';
import { useRecommendations } from '../features/recommendations/useRecommendations.js';
import { Recommendations } from '../features/recommendations/Recommendations.jsx';
import { useLearningPlan } from '../features/learning-plan/useLearningPlan.js';
import { LearningPlan } from '../features/learning-plan/LearningPlan.jsx';
import { Onboarding } from '../features/onboarding/Onboarding.jsx';
import { MaterialDialog } from '../shared/ui/MaterialDialog.jsx';
const EXAMPLES=['Хочу научиться управлять командой','Как давать обратную связь сотрудникам','Как автоматизировать бизнес с ИИ'];
export default function App(){
 const auth=useAuth();
 const [generation,setGeneration]=useState(null),[healthError,setHealthError]=useState(''),[tab,setTab]=useState('search'),[catalogSource,setCatalogSource]=useState('demo');
 const [modal,setModal]=useState(null),[modalBusy,setModalBusy]=useState(false),[modalError,setModalError]=useState('');
 const [onboarding,setOnboarding]=useState(false),[mobileMenu,setMobileMenu]=useState(false),[profileReady,setProfileReady]=useState(false);
 const profileState=useProfile();const {profile}=profileState;
 const search=useSearch(generation,()=>{refreshGeneration()});
 const recommendations=useRecommendations(),plan=useLearningPlan(),catalog=useCatalog();
 async function refreshGeneration(){try{const state=await api.health();setGeneration(state.generation);setHealthError('');await profileState.refresh();await catalog.load(state.generation);}
 catch(e){setHealthError(e.message)}}
 useEffect(()=>{if(!auth.authenticated){setProfileReady(false);return;}
  let cancelled=false;const c=new AbortController();
  Promise.all([api.health(c.signal),profileState.refresh()]).then(([health])=>{if(!cancelled){setGeneration(health.generation);setProfileReady(true);setHealthError('');catalog.load(health.generation)}})
    .catch(e=>{if(!cancelled)setHealthError(e.message)});
  return()=>{cancelled=true;c.abort()};
 },[auth.authenticated]);
 function navigate(next){setMobileMenu(false);search.cancel();recommendations.cancel();plan.cancel();setTab(next);if(next==='recommend')recommendations.load(generation);if(next==='plan')plan.load(generation)}
 function runSearch(q=search.query,k=search.kind,options={}){navigate('search');search.search(q,k,options)}
 async function handleFinish(data){await profileState.saveProfile({...profile,...data});setOnboarding(false);setTab('recommend');recommendations.load(generation)}
 async function setInterests(categories){try{await profileState.saveProfile({...profile,categories})}catch(e){setHealthError(e.message)}}
 async function openMaterial(item){setModal(item);setModalError('');try{await profileState.addActivity(item,'viewed',generation)}catch(e){setModalError(`Не удалось сохранить просмотр: ${e.message}`)}}
 async function completeMaterial(item){setModalBusy(true);setModalError('');try{await profileState.addActivity(item,'completed',generation);setModal(null)}catch(e){setModalError(e.message)}finally{setModalBusy(false)}}
 function clicked(item,action){profileState.addActivity(item,action,generation).catch(()=>{});}
 async function logout(){catalog.clear();try{await auth.logout()}catch(e){setHealthError(e.message)}finally{profileState.clear();setGeneration(null);setModal(null)}}
 const headings={search:search.submitted?'Результаты поиска':'Каталог образовательных материалов',recommend:'Подобрано для вас',plan:'Ваш учебный маршрут'};
 const subtitles={search:search.submitted?`По запросу: «${search.submitted}»`:'Изучите доступные курсы и статьи или найдите материал под свою задачу.',recommend:'Подбор по сохранённым интересам и активности.',plan:'Следующие тематические шаги по вашей истории.'};
 if(auth.status==='checking')return <div className="auth-layout"><p>Проверяем сессию...</p></div>;
 if(!auth.authenticated)return <AuthScreen auth={auth}/>;
 return <div className="app-root alfa-original"><header className="topbar"><div className="shell header-in">
  <a className="brand" href="#" onClick={e=>{e.preventDefault();navigate('search')}}><span className="brand-mark">А</span><span>альфа<span className="brand-light">курс</span></span></a>
  <nav className={mobileMenu?'open':''}><a href="https://kurs.alfabank.ru/" target="_blank" rel="noreferrer">Каталог обучения <ArrowUpRight size={13}/></a><button onClick={()=>navigate('search')}>Умный подбор</button><button onClick={()=>navigate('recommend')}>Для вас</button><button onClick={()=>navigate('plan')}>Мой маршрут</button></nav>
  <div className="header-right"><span className="demo-pill"><span/>{auth.username}</span><button className="outline" onClick={logout}>Выйти</button><button className="menu-btn" onClick={()=>setMobileMenu(x=>!x)} aria-label="Открыть меню">{mobileMenu?<X/>:<Menu/>}</button></div>
 </div></header>
 <main><section className="hero"><div className="shell hero-inner"><div className="hero-content"><span className="eyebrow"><Sparkles size={15}/> ПЕРСОНАЛЬНЫЙ ПОИСК ЗНАНИЙ</span><h1>Знания для <em>вашей</em> задачи.</h1><p className="subtitle">Опишите, что хотите узнать или чему научиться. Найдём подходящие образовательные материалы.</p>
 <SearchBar state={search} onSearch={runSearch}/><div className="examples"><span>Попробуйте:</span>{EXAMPLES.map(example=><button key={example} onClick={()=>runSearch(example)}>{example} <ArrowUpRight size={13}/></button>)}</div>
 <button className="onboarding-link" onClick={()=>setOnboarding(true)}><Target size={17}/> Не знаете, с чего начать? Пройдите короткий опрос <ArrowRight size={16}/></button>
 </div><div className="hero-art" aria-hidden="true"><div className="hero-blob"><div className="floating-card card-one"><span><Target size={19}/></span><div><b>Ваша цель</b><small>Развитие бизнеса</small></div><Check size={17}/></div><div className="floating-card card-two"><span><BookOpen size={19}/></span><div><b>Подходящие знания</b><small>Курсы и статьи</small></div><ArrowRight size={17}/></div></div></div></div></section>
 <section className="workspace shell"><div className="tabs" role="tablist" aria-label="Разделы"><button role="tab" aria-selected={tab==='search'} className={tab==='search'?'active':''} onClick={()=>navigate('search')}><Search size={18}/>Поиск</button><button role="tab" aria-selected={tab==='recommend'} className={tab==='recommend'?'active':''} onClick={()=>navigate('recommend')}><Sparkles size={18}/>Для вас</button><button role="tab" aria-selected={tab==='plan'} className={tab==='plan'?'active':''} onClick={()=>navigate('plan')}><Compass size={18}/>Учебный маршрут</button></div>
 <div className="workspace-heading"><div><span className="section-kicker">РЕКОМЕНДАЦИИ АЛЬФА-КУРСА</span><h2>{headings[tab]}</h2><p>{subtitles[tab]}</p></div>{tab==='search'&&search.submitted&&<button className="outline" onClick={()=>search.reset()}>Вернуться к каталогу</button>}</div>
 {healthError&&<p className="notice" role="alert">{healthError} <button className="outline" onClick={refreshGeneration}>Повторить</button></p>}
 {!profileReady?<p>Загружаем профиль...</p>:tab==='search'?(search.submitted?<SearchResults state={search} profile={profileState} onOpen={openMaterial}/>:<><div className="filterbar" aria-label="Источник каталога"><button className={catalogSource==='demo'?'selected':''} onClick={()=>setCatalogSource('demo')}>Демо: все карточки</button><button className={catalogSource==='model'?'selected':''} onClick={()=>setCatalogSource('model')}>Каталог алгоритма</button></div>{catalogSource==='demo'?<DemoCatalog/>:<Catalog state={catalog} profile={profileState} onOpen={openMaterial} onFilter={kind=>catalog.load(generation,kind)} onMore={()=>catalog.load(generation,catalog.kind,true)} onRetry={()=>catalog.load(generation,catalog.kind)}/>}</>):tab==='recommend'?<Recommendations state={recommendations} profile={profileState} onOpen={openMaterial} onInterests={setInterests} onRetry={()=>recommendations.load(generation)} onOnboarding={()=>setOnboarding(true)}/>:<LearningPlan state={plan} onOpen={openMaterial} onRetry={()=>plan.load(generation)}/>}
 {tab==='recommend'&&profile.goal&&<div className="onboarding-goal"><strong>Ваша цель:</strong> {profile.goal}<button className="outline" onClick={()=>runSearch(profile.goal)}>Найти по цели <Search size={15}/></button></div>}
 </section><section className="bottom-banner"><div className="shell banner-inner"><div><span>ОБРАЗОВАНИЕ ДЛЯ БИЗНЕСА</span><h2>Развивайте дело.<br/>Знания мы поможем найти.</h2></div><a href="https://kurs.alfabank.ru/" target="_blank" rel="noreferrer">На Альфа-Курс <ArrowUpRight size={18}/></a></div></section></main>
 <footer className="shell footer"><span>альфа<span>курс</span></span><p>Демо-сервис. История и анкета сохраняются на сервере. Завершение курса — отметка пользователя.</p><a href="https://github.com/KaNaP1A/alfa_hakaton" target="_blank" rel="noreferrer">GitHub <ArrowUpRight size={14}/></a></footer>
 {modal&&createPortal(<MaterialDialog item={modal} completed={profileState.completed.includes(modal.entity_key)} busy={modalBusy} error={modalError} onComplete={completeMaterial} onStarted={clicked} onClose={()=>setModal(null)}/>,document.body)}
 {onboarding&&createPortal(<Onboarding initial={{...profile,goal:profile.goal||''}} onFinish={handleFinish} onClose={()=>setOnboarding(false)}/>,document.body)}
 </div>;
}
