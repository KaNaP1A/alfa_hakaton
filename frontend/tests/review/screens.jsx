// Visual QA only: existing public benchmark fixtures, never loaded by the application.
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fs from "node:fs";
import { Workspace } from "../../src/app/Workspace.jsx";
import { AuthScreen } from "../../src/features/auth/AuthScreen.jsx";
import { MaterialDialog } from "../../src/shared/ui/MaterialDialog.jsx";
import { Onboarding } from "../../src/features/onboarding/Onboarding.jsx";
const fixtures = JSON.parse(
  fs.readFileSync(
    new URL("../../../data/synthetic/test/catalog.json", import.meta.url),
  ),
);
const selected = [
  ...fixtures.filter((x) => x.kind === "course").slice(0, 3),
  ...fixtures.filter((x) => x.kind !== "course").slice(0, 3),
].map((x) => ({ ...x, price: { status: "unknown" }, access_verified: true }));
const noop = () => {};
const profile = {
  categories: ["business", "finance"],
  goal: "Открыть своё дело",
};
const shared = {
  auth: { username: "Эксперт", status: "guest" },
  tab: "search",
  catalogSource: "model",
  setCatalogSource: noop,
  navigate: noop,
  mobileMenu: false,
  setMobileMenu: noop,
  search: {
    query: "",
    submitted: "",
    kind: "",
    loading: false,
    suggestions: [],
    relatedTopics: [],
    suggestOpen: false,
    reset: noop,
  },
  catalog: {
    items: selected,
    kind: "",
    loaded: true,
    loading: false,
    total: fixtures.length,
  },
  recommendations: { loading: false, data: { results: selected.slice(0, 3) } },
  plan: {
    loading: false,
    data: {
      steps: selected
        .slice(0, 3)
        .map((material, i) => ({
          number: i + 1,
          material,
          why: "Тематическая рекомендация по вашей истории",
        })),
    },
  },
  profileState: { profile, viewed: [], completed: [] },
  profileReady: true,
  generation: "qa-fixture",
  healthError: "",
  refreshGeneration: noop,
  runSearch: noop,
  setOnboarding: noop,
  setInterests: noop,
  setFacets: noop,
  interests: { categories: profile.categories, saving: false, error: "" },
  openMaterial: noop,
  logout: noop,
};
export const screens = {
  catalog: renderToStaticMarkup(<Workspace {...shared} />),
  recommendations: renderToStaticMarkup(
    <Workspace {...shared} tab="recommend" />,
  ),
  plan: renderToStaticMarkup(<Workspace {...shared} tab="plan" />),
  empty: renderToStaticMarkup(
    <Workspace
      {...shared}
      catalog={{ ...shared.catalog, items: [], total: 0 }}
    />,
  ),
  search: renderToStaticMarkup(
    <Workspace
      {...shared}
      search={{
        ...shared.search,
        query: "Налоги для ИП",
        submitted: "Налоги для ИП",
        result: {
          results: selected.slice(0, 2),
          clarification: {
            question: "Уточните вашу задачу",
            options: [
              { label: "Для начинающего предпринимателя", token: "fixture" },
            ],
            allow_text: true,
          },
        },
      }}
    />,
  ),
  material: renderToStaticMarkup(
    <>
      <Workspace {...shared} />
      <MaterialDialog
        item={selected[0]}
        completed={false}
        onClose={noop}
        onComplete={noop}
        onStarted={noop}
      />
    </>,
  ),
  onboarding: renderToStaticMarkup(
    <>
      <Workspace {...shared} />
      <Onboarding initial={profile} onFinish={noop} onClose={noop} />
    </>,
  ),
  login: renderToStaticMarkup(
    <AuthScreen auth={{ status: "guest", authenticate: noop }} />,
  ),
};
