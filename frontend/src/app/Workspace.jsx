import React from "react";
import {
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  Search,
  SlidersHorizontal,
  Route,
  UserRound,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { Brand } from "../shared/ui/Brand.jsx";
import { SearchBar } from "../features/search/SearchBar.jsx";
import { Catalog } from "../features/catalog/Catalog.jsx";
import { DemoCatalog } from "../features/catalog/DemoCatalog.jsx";
import { SearchResults } from "../features/search/SearchResults.jsx";
import { Recommendations } from "../features/recommendations/Recommendations.jsx";
import { LearningPlan } from "../features/learning-plan/LearningPlan.jsx";
import { State } from "../shared/ui/ResultStates.jsx";
import { useDialog } from "../shared/ui/useDialog.js";

const EXAMPLES = [
  "Как открыть кофейню",
  "Найм первого сотрудника",
  "Налоги для ИП",
];
const NAV = [
  ["search", "Каталог", Search],
  ["recommend", "Для вас", SlidersHorizontal],
  ["plan", "Мой маршрут", Route],
];
export function Workspace({
  auth,
  tab,
  catalogSource,
  setCatalogSource,
  navigate,
  mobileMenu,
  setMobileMenu,
  search,
  catalog,
  recommendations,
  plan,
  profileState,
  profileReady,
  generation,
  healthError,
  refreshGeneration,
  runSearch,
  setOnboarding,
  setInterests,
  setFacets,
  interests,
  openMaterial,
  logout,
}) {
  const menuRef = useDialog(() => setMobileMenu(false), mobileMenu);
  const isSearch = tab === "search";
  const titles = {
    search: search.submitted ? "Результаты поиска" : "Все материалы",
    recommend: "Подобрано для вас",
    plan: "Ваш учебный маршрут",
  };
  const heading = {
    search: "Знания для вашего бизнеса",
    recommend: "Обучение, которое вам подходит",
    plan: "От интереса к новым знаниям",
  };
  const intro = {
    search:
      "Курсы, статьи и практические материалы. Найдите то, что поможет решить вашу задачу.",
    recommend:
      "Ваши интересы и изученные материалы помогают выбрать, что посмотреть дальше.",
    plan: "Последовательность материалов по темам, которые вы уже изучаете.",
  };
  const profile = profileState.profile;
  return (
    <div className="app-root">
      <header className="site-header">
        <div className="shell wrap header-inner">
          <a className="skip-link" href="#main">
            К содержимому
          </a>
          <Brand
            onClick={(e) => {
              e.preventDefault();
              search.reset();
              navigate("search");
            }}
          />
          <nav
            ref={menuRef}
            className={mobileMenu ? "main-nav is-open" : "main-nav"}
            aria-label="Основная навигация"
            id="main-navigation"
          >
            {NAV.map(([value, label, Icon]) => (
              <button
                key={value}
                className={tab === value ? "active" : ""}
                aria-current={tab === value ? "page" : undefined}
                onClick={() => navigate(value)}
              >
                <Icon size={18} />
                <span>{label}</span>
              </button>
            ))}
            <button className="mobile-logout" onClick={logout}>
              <LogOut size={18} />
              Выйти из аккаунта
            </button>
            <a
              className="mobile-source-link"
              href="https://kurs.alfabank.ru/"
              target="_blank"
              rel="noreferrer"
            >
              Об Альфа-Курсе <ArrowUpRight size={16} />
            </a>
          </nav>
          <div className="header-actions">
            <button
              className="profile-button"
              onClick={() => setOnboarding(true)}
              aria-label={`Изменить интересы, ${auth.username}`}
            >
              <span className="avatar">
                <UserRound size={18} />
              </span>
              <span className="profile-name">{auth.username}</span>
            </button>
            <button
              className="icon-button logout-button"
              onClick={logout}
              aria-label="Выйти из аккаунта"
            >
              <LogOut size={19} />
            </button>
            <button
              className="icon-button menu-toggle"
              aria-label={mobileMenu ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={mobileMenu}
              aria-controls="main-navigation"
              onClick={() => setMobileMenu((v) => !v)}
            >
              {mobileMenu ? <X /> : <Menu />}
            </button>
          </div>
        </div>
      </header>
      <main id="main" inert={mobileMenu ? "" : undefined}>
        <div className="shell breadcrumbs">
          <span>Альфа-Курс</span>
          <ChevronRight size={14} />
          <span>{NAV.find(([value]) => value === tab)?.[1]}</span>
        </div>
        <div className="shell wrap intro-panel hero" data-enter="">
          <div className="intro-copy">
            <span className="product-label">
              <span className="red-dot" /> Персональный подбор
            </span>
            <h1>{heading[tab]}</h1>
            <p>{intro[tab]}</p>
          </div>
          <button
            className="interest-invitation"
            onClick={() => setOnboarding(true)}
          >
            <span className="invitation-icon">
              <SlidersHorizontal size={24} />
            </span>
            <span>
              <strong>
                {profile.categories.length ? "Ваши интересы" : "С чего начать?"}
              </strong>
              <span>
                {profile.categories.length
                  ? "Изменить подборку тем"
                  : "Подберите обучение под себя"}
              </span>
            </span>
            <ArrowUpRight size={21} />
          </button>
          {isSearch && (
            <div className="search-block">
              <SearchBar state={search} onSearch={runSearch} />
              <div className="query-examples">
                <span>Например</span>
                {EXAMPLES.map((text) => (
                  <button key={text} onClick={() => runSearch(text)}>
                    {text}
                    <ArrowUpRight size={14} />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <section
          className="shell wrap catalog-workspace"
          aria-labelledby="workspace-title"
          id="materials"
        >
          <div className="workspace-heading">
            <div>
              <h2 id="workspace-title">
                {titles[tab]}
                {isSearch && !search.submitted && catalogSource === "model" && catalog.loaded && (
                  <span className="result-total">
                    {new Intl.NumberFormat("ru-RU").format(catalog.total)}
                  </span>
                )}
              </h2>
              {isSearch && search.submitted && (
                <p>По запросу «{search.submitted}»</p>
              )}
            </div>
            {isSearch && search.submitted ? (
              <button
                className="outline btn btn--secondary"
                onClick={search.reset}
              >
                Вернуться к каталогу
              </button>
            ) : (
              <span className="workspace-note">
                {isSearch
                  ? "Найдите свой формат обучения"
                  : tab === "recommend"
                    ? "Подборка по вашим интересам"
                    : "Шаг за шагом"}
              </span>
            )}
          </div>
          {healthError && (
            <div className="notice" role="alert">
              <span>{healthError}</span>
              <button className="text-btn" onClick={refreshGeneration}>
                Повторить загрузку
              </button>
            </div>
          )}
          {isSearch && !search.submitted && (
            <div className="catalog-source-switch filterbar" role="group" aria-label="Источник каталога">
              <button
                className={catalogSource === "demo" ? "selected" : ""}
                aria-pressed={catalogSource === "demo"}
                onClick={() => setCatalogSource("demo")}
              >
                Демо: все карточки
              </button>
              <button
                className={catalogSource === "model" ? "selected" : ""}
                aria-pressed={catalogSource === "model"}
                onClick={() => setCatalogSource("model")}
              >
                Каталог алгоритма
              </button>
            </div>
          )}
          {!profileReady ? (
            <State loading />
          ) : isSearch ? (
            search.submitted ? (
              <SearchResults
                state={search}
                profile={profileState}
                onOpen={openMaterial}
              />
            ) : catalogSource === "demo" ? (
              <DemoCatalog
                onUseModel={() => setCatalogSource("model")}
                onOpenRecommendations={() => navigate("recommend")}
              />
            ) : (
              <Catalog
                state={catalog}
                profile={profileState}
                onOpen={openMaterial}
                onFilter={(kind) => catalog.load(generation, kind)}
                onMore={() => catalog.load(generation, catalog.kind, true)}
                onRetry={() => catalog.load(generation, catalog.kind)}
              />
            )
          ) : tab === "recommend" ? (
            <Recommendations
              generation={generation}
              state={recommendations}
              profile={profileState}
              onOpen={openMaterial}
              selectedCategories={interests.categories}
              onInterests={setInterests}
              onFacets={setFacets}
              savingInterests={interests.saving}
              interestsError={interests.error}
              onRetry={() => recommendations.load(generation)}
              onOnboarding={() => setOnboarding(true)}
            />
          ) : (
            <LearningPlan
              state={plan}
              onOpen={openMaterial}
              onRetry={() => plan.load(generation)}
            />
          )}
          {tab === "recommend" && profile.goal && (
            <div className="saved-goal">
              <span>
                <span className="field-help">Ваша цель</span>
                <strong>{profile.goal}</strong>
              </span>
              <button
                className="outline btn btn--secondary"
                onClick={() => runSearch(profile.goal)}
              >
                Найти по цели <Search size={16} />
              </button>
            </div>
          )}
        </section>
        {tab !== "plan" && (
          <div className="shell learning-note">
            <div className="note-mark">
              <Route size={26} />
            </div>
            <div>
              <h2>Каждая задача — повод узнать больше</h2>
              <p>
                Смотрите материалы, отмечайте изученное и возвращайтесь за
                следующими шагами.
              </p>
            </div>
            <button
              className="outline btn btn--secondary"
              onClick={() => navigate("plan")}
            >
              Открыть маршрут <ArrowRight size={16} />
            </button>
          </div>
        )}
      </main>
      <footer className="site-footer">
        <div className="shell footer-inner">
          <Brand
            onClick={(e) => {
              e.preventDefault();
              window.scrollTo({ top: 0, behavior: "instant" });
            }}
          />
          <span>Персональная траектория обучения для вашего дела</span>
          <a
            className="reference-link"
            href="https://kurs.alfabank.ru/"
            target="_blank"
            rel="noreferrer"
          >
            Об Альфа-Курсе <ArrowUpRight size={16} />
          </a>
        </div>
      </footer>
    </div>
  );
}
