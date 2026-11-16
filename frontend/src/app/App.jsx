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
import { useRecommendations } from '../features/recommendations/useRecommendations.js';
import { Recommendations } from '../features/recommendations/Recommendations.jsx';
import { useAutoInterests } from '../features/recommendations/useAutoInterests.js';
import { useLearningPlan } from '../features/learning-plan/useLearningPlan.js';
import { LearningPlan } from '../features/learning-plan/LearningPlan.jsx';
import { Onboarding } from '../features/onboarding/Onboarding.jsx';
import { MaterialDialog } from '../shared/ui/MaterialDialog.jsx';
const EXAMPLES=['Хочу научиться управлять командой','Как давать обратную связь сотрудникам','Как автоматизировать бизнес с ИИ'];
export default function App(){
 const auth=useAuth();
 const [generation,setGeneration]=useState(null),[healthError,setHealthError]=useState(''),[tab,setTab]=useState('search');
 const [modal,setModal]=useState(null),[modalBusy,setModalBusy]=useState(false),[modalError,setModalError]=useState('');
 const [onboarding,setOnboarding]=useState(false),[mobileMenu,setMobileMenu]=useState(false),[profileReady,setProfileReady]=useState(false);
 const profileState=useProfile();const {profile}=profileState;
 const search=useSearch(generation,()=>{refreshGeneration()});
 const recommendations=useRecommendations(),plan=useLearningPlan(),catalog=useCatalog();
 const interests=useAutoInterests({
   profile,
   saveProfile:data=>profileState.saveProfile({...data,selected_facets:[]}),
   refreshRecommendations:recommendations.load,
   generation,
   active:tab==='recommend',
 });
 async function refreshGeneration(){try{const state=await api.health();setGeneration(state.generation);setHealthError('');await profileState.refresh();setProfileReady(true);await catalog.load(state.generation);}
 catch(e){setHealthError(e.message)}}
 useEffect(()=>{if(!auth.authenticated){interests.reset();setProfileReady(false);return;}
  let cancelled=false;const c=new AbortController();
  Promise.all([api.health(c.signal),profileState.refresh()]).then(([health])=>{if(!cancelled){setGeneration(health.generation);setProfileReady(true);setHealthError('');catalog.load(health.generation)}})
    .catch(e=>{if(!cancelled)setHealthError(e.message)});
  return()=>{cancelled=true;c.abort()};
 },[auth.authenticated]);
 function navigate(next){setMobileMenu(false);search.cancel();recommendations.cancel();plan.cancel();setTab(next);if(next==='recommend')recommendations.load(generation);if(next==='plan')plan.load(generation)}
 function runSearch(q=search.query,k=search.kind,options={}){navigate('search');search.search(q,k,options)}
 async function handleFinish(data){
   await interests.resetAndWait();
   await profileState.saveProfile({...profile,...data,selected_facets:[]});
   setOnboarding(false);setTab('recommend');recommendations.load(generation);
 }
 function setInterests(categories){
   recommendations.cancel();
   interests.choose(categories);
 }
 async function setFacets(selected_facets){
   try{await profileState.saveProfile({...profile,selected_facets});await recommendations.load(generation)}
   catch(e){setHealthError(e.message);throw e}
 }
 async function openMaterial(item){setModal(item);setModalError('');try{await profileState.addActivity(item,'viewed',generation)}catch(e){setModalError(`Не удалось сохранить просмотр: ${e.message}`)}}
 async function completeMaterial(item){setModalBusy(true);setModalError('');try{await profileState.addActivity(item,'completed',generation);setModal(null)}catch(e){setModalError(e.message)}finally{setModalBusy(false)}}
 function clicked(item,action){profileState.addActivity(item,action,generation).catch(e=>setModalError(`Не удалось сохранить переход: ${e.message}`));}
 async function logout(){await interests.resetAndWait();await profileState.waitForSaves();catalog.clear();try{await auth.logout()}catch(e){setHealthError(e.message)}finally{profileState.clear();setGeneration(null);setModal(null)}}
 const headings={search:search.submitted?'Результаты поиска':'Каталог образовательных материалов',recommend:'Подобрано для вас',plan:'Ваш учебный маршрут'};
 const subtitles={search:search.submitted?`По запросу: «${search.submitted}»`:'Изучите доступные курсы и статьи или найдите материал под свою задачу.',recommend:'Подбор по сохранённым интересам и активности.',plan:'Следующие тематические шаги по вашей истории.'};
 if(auth.status==='checking')return <div className="auth-layout"><p>Проверяем сессию...</p></div>;
 if(!auth.authenticated)return <AuthScreen auth={auth}/>;
 return <div className="app-root alfa-original"><header className="topbar"><div className="shell header-in">
  <a className="brand" href="#" onClick={e=>{e.preventDefault();navigate('search')}}><span className="brand-mark">А</span><span>альфа<span className="brand-light">курс</span></span></a>
  <nav id="main-navigation" aria-label="Основное меню" className={mobileMenu?'open':''}><button onClick={()=>navigate('search')}>Каталог материалов</button><button onClick={()=>navigate('search')}>Умный подбор</button><button onClick={()=>navigate('recommend')}>Для вас</button><button onClick={()=>navigate('plan')}>Мой маршрут</button></nav>
  <div className="header-right"><span className="demo-pill"><span/>{auth.username}</span><button className="outline" onClick={logout}>Выйти</button><button className="menu-btn" aria-expanded={mobileMenu} aria-controls="main-navigation" onClick={()=>setMobileMenu(x=>!x)} aria-label={mobileMenu?"Закрыть меню":"Открыть меню"}>{mobileMenu?<X/>:<Menu/>}</button></div>
 </div></header>
 <main><section className="hero"><div className="shell hero-inner"><div className="hero-content"><h1>Найдите знания под свою задачу</h1><p className="subtitle">Опишите, чему хотите научиться или какой вопрос решить. Подберём курсы и полезные материалы.</p>
 <SearchBar state={search} onSearch={runSearch}/><div className="examples"><span>Примеры запросов</span>{EXAMPLES.map(example=><button key={example} onClick={()=>runSearch(example)}>{example} <ArrowUpRight size={13}/></button>)}</div>
 <button className="onboarding-link" onClick={()=>setOnboarding(true)}><Target size={17}/> Не знаете, с чего начать? Пройдите короткий опрос <ArrowRight size={16}/></button>
 </div><div className="hero-art" aria-hidden="true"><div className="hero-blob"><div className="floating-card card-one"><span><Target size={19}/></span><div><b>Ваша цель</b><small>Развитие бизнеса</small></div><Check size={17}/></div><div className="floating-card card-two"><span><BookOpen size={19}/></span><div><b>Подходящие знания</b><small>Курсы и статьи</small></div><ArrowRight size={17}/></div></div></div></div></section>
 <section className="workspace shell" id="materials"><div className="tabs" role="group" aria-label="Разделы"><button aria-pressed={tab==='search'} className={tab==='search'?'active':''} onClick={()=>navigate('search')}><Search size={18}/>Поиск</button><button aria-pressed={tab==='recommend'} className={tab==='recommend'?'active':''} onClick={()=>navigate('recommend')}><Sparkles size={18}/>Для вас</button><button aria-pressed={tab==='plan'} className={tab==='plan'?'active':''} onClick={()=>navigate('plan')}><Compass size={18}/>Учебный маршрут</button></div>
 <div className="workspace-heading"><div><h2>{headings[tab]}</h2><p>{subtitles[tab]}</p></div>{tab==='search'&&search.submitted&&<button className="outline" onClick={()=>search.reset()}>Вернуться к каталогу</button>}</div>
 {healthError&&<p className="notice" role="alert">{healthError} <button className="outline" onClick={refreshGeneration}>Повторить</button></p>}
 {!profileReady?<p>Загружаем профиль...</p>:tab==='search'?(search.submitted?<SearchResults state={search} profile={profileState} onOpen={openMaterial}/>:<Catalog state={catalog} profile={profileState} onOpen={openMaterial} onFilter={kind=>catalog.load(generation,kind)} onMore={()=>catalog.load(generation,catalog.kind,true)} onRetry={()=>catalog.load(generation,catalog.kind)}/>):tab==='recommend'?<Recommendations generation={generation} state={recommendations} profile={profileState} onOpen={openMaterial} selectedCategories={interests.categories} onInterests={setInterests} onFacets={setFacets} savingInterests={interests.saving} interestsError={interests.error} onRetry={()=>recommendations.load(generation)} onOnboarding={()=>setOnboarding(true)}/>:<LearningPlan state={plan} onOpen={openMaterial} onRetry={()=>plan.load(generation)}/>}
 {tab==='recommend'&&profile.goal&&<div className="onboarding-goal"><strong>Ваша цель:</strong> {profile.goal}<button className="outline" onClick={()=>runSearch(profile.goal)}>Найти по цели <Search size={15}/></button></div>}
 </section><section className="bottom-banner"><div className="shell banner-inner"><div><h2>Развивайте дело.<br/>Знания мы поможем найти.</h2></div><button type="button" className="primary" onClick={()=>{navigate('search');document.getElementById('materials')?.scrollIntoView({behavior:'smooth'})}}>Посмотреть материалы <ArrowRight size={18}/></button></div></section></main>
 <footer className="shell footer"><span>альфа<span>курс</span></span><p>Подбор образовательных материалов под ваши задачи. Отметки о прохождении добавляются вами.</p></footer>
 {modal&&createPortal(<MaterialDialog item={modal} completed={profileState.completed.includes(modal.entity_key)} busy={modalBusy} error={modalError} onComplete={completeMaterial} onStarted={clicked} onClose={()=>setModal(null)}/>,document.body)}
 {onboarding&&createPortal(<Onboarding initial={{...profile,categories:interests.categories,goal:profile.goal||''}} onFinish={handleFinish} onClose={()=>setOnboarding(false)}/>,document.body)}
 </div>;
}
