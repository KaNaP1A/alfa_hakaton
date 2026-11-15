import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Workspace } from "./Workspace.jsx";
import { api } from "../shared/api/index.js";
import { useAuth } from "../features/auth/useAuth.js";
import { AuthScreen } from "../features/auth/AuthScreen.jsx";
import { useProfile } from "../features/profile/useProfile.js";
import { useSearch } from "../features/search/useSearch.js";
import { useCatalog } from "../features/catalog/useCatalog.js";
import { useRecommendations } from "../features/recommendations/useRecommendations.js";
import { useLearningPlan } from "../features/learning-plan/useLearningPlan.js";
import { Onboarding } from "../features/onboarding/Onboarding.jsx";
import { MaterialDialog } from "../shared/ui/MaterialDialog.jsx";
export default function App() {
  const auth = useAuth();
  useEffect(() => {
    window.AlfaCourseMotion?.refresh();
  }, [auth.authenticated, auth.status]);
  const [generation, setGeneration] = useState(null),
    [healthError, setHealthError] = useState(""),
    [tab, setTab] = useState("search");
  const [catalogSource, setCatalogSource] = useState("model");
  const [modal, setModal] = useState(null),
    [modalBusy, setModalBusy] = useState(false),
    [modalError, setModalError] = useState("");
  const [onboarding, setOnboarding] = useState(false),
    [mobileMenu, setMobileMenu] = useState(false),
    [profileReady, setProfileReady] = useState(false);
  const profileState = useProfile();
  const { profile } = profileState;
  const search = useSearch(generation, () => {
    refreshGeneration();
  });
  const recommendations = useRecommendations(),
    plan = useLearningPlan(),
    catalog = useCatalog();
  async function refreshGeneration() {
    try {
      const state = await api.health();
      setGeneration(state.generation);
      setHealthError("");
      await profileState.refresh();
      await catalog.load(state.generation);
    } catch (e) {
      setHealthError(e.userMessage || e.message);
    }
  }
  useEffect(() => {
    if (!auth.authenticated) {
      setProfileReady(false);
      return;
    }
    let cancelled = false;
    const c = new AbortController();
    Promise.all([api.health(c.signal), profileState.refresh()])
      .then(([health]) => {
        if (!cancelled) {
          setGeneration(health.generation);
          setProfileReady(true);
          setHealthError("");
          catalog.load(health.generation);
        }
      })
      .catch((e) => {
        if (!cancelled) setHealthError(e.userMessage || e.message);
      });
    return () => {
      cancelled = true;
      c.abort();
    };
  }, [auth.authenticated]);
  function navigate(next) {
    setMobileMenu(false);
    search.cancel();
    recommendations.cancel();
    plan.cancel();
    setTab(next);
    if (next === "recommend") recommendations.load(generation);
    if (next === "plan") plan.load(generation);
  }
  function runSearch(q = search.query, k = search.kind, options = {}) {
    navigate("search");
    search.search(q, k, options);
  }
  async function handleFinish(data) {
    await profileState.saveProfile({ ...profile, ...data });
    setOnboarding(false);
    setTab("recommend");
    recommendations.load(generation);
  }
  async function setInterests(categories) {
    try {
      await profileState.saveProfile({ ...profile, categories });
    } catch (e) {
      setHealthError(e.userMessage || e.message);
    }
  }
  async function openMaterial(item) {
    setModal(item);
    setModalError("");
    try {
      await profileState.addActivity(item, "viewed", generation);
    } catch (e) {
      setModalError(
        `Не удалось сохранить просмотр: ${e.userMessage || e.message}`,
      );
    }
  }
  async function completeMaterial(item) {
    setModalBusy(true);
    setModalError("");
    try {
      await profileState.addActivity(item, "completed", generation);
      setModal(null);
    } catch (e) {
      setModalError(e.userMessage || e.message);
    } finally {
      setModalBusy(false);
    }
  }
  function clicked(item, action) {
    profileState.addActivity(item, action, generation).catch(() => {});
  }
  async function logout() {
    catalog.clear();
    try {
      await auth.logout();
    } catch (e) {
      setHealthError(e.userMessage || e.message);
    } finally {
      profileState.clear();
      setGeneration(null);
      setModal(null);
    }
  }
  if (auth.status === "checking")
    return (
      <div className="auth-layout">
        <p>Проверяем сессию...</p>
      </div>
    );
  if (!auth.authenticated) return <AuthScreen auth={auth} />;
  return (
    <>
      <Workspace
        {...{
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
          openMaterial,
          logout,
        }}
      />
      {modal &&
        createPortal(
          <MaterialDialog
            item={modal}
            completed={profileState.completed.includes(modal.entity_key)}
            busy={modalBusy}
            error={modalError}
            onComplete={completeMaterial}
            onStarted={clicked}
            onClose={() => setModal(null)}
          />,
          document.body,
        )}
      {onboarding &&
        createPortal(
          <Onboarding
            initial={{ ...profile, goal: profile.goal || "" }}
            onFinish={handleFinish}
            onClose={() => setOnboarding(false)}
          />,
          document.body,
        )}
    </>
  );
}
