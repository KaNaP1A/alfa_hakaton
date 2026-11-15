import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import React, { act } from "react";
import { AuthScreen } from "../src/features/auth/AuthScreen.jsx";
import { SearchBar } from "../src/features/search/SearchBar.jsx";
import { MaterialCard } from "../src/shared/ui/MaterialCard.jsx";
import { MaterialDialog } from "../src/shared/ui/MaterialDialog.jsx";
import { Onboarding } from "../src/features/onboarding/Onboarding.jsx";
let dom, root, container;
beforeEach(async () => {
  dom = new JSDOM(
    '<!doctype html><html><body><button id="previous">Open</button><div id="root"></div></body></html>',
    { url: "http://localhost/" },
  );
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.HTMLElement = dom.window.HTMLElement;
  globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
  globalThis.cancelAnimationFrame = clearTimeout;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const { createRoot } = await import("react-dom/client");
  container = document.getElementById("root");
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  dom.window.close();
  delete globalThis.window;
  delete globalThis.document;
});
const click = async (element) => {
  assert.ok(element);
  await act(async () => element.click());
};
const item = {
  entity_key: "course:fixture",
  kind: "course",
  title: "Управление командой",
  description: "Учебный материал",
  topics: ["Команда"],
  access_verified: true,
  price: { status: "unknown" },
};

test("registration submits through the supplied auth adapter; password visibility is reversible", async () => {
  let request;
  await act(async () =>
    root.render(
      <AuthScreen
        auth={{
          status: "guest",
          authenticate: async (...args) => {
            request = args;
          },
        }}
      />,
    ),
  );
  await click(
    [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Регистрация",
    ),
  );
  assert.match(container.textContent, /Создать аккаунт/);
  const password = container.querySelector("#password");
  assert.equal(password.type, "password");
  await click(container.querySelector('[aria-label="Показать пароль"]'));
  assert.equal(password.type, "text");
  await click(container.querySelector('[aria-label="Скрыть пароль"]'));
  assert.equal(password.type, "password");
  const username = container.querySelector("#username");
  assert.equal(
    new RegExp("^" + username.pattern + "$", "v").test("expert-review"),
    true,
  );
  for (const [field, value] of [
    [username, "expert-review"],
    [password, "long-test-password"],
  ]) {
    Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set.call(field, value);
    await act(async () =>
      field.dispatchEvent(new window.Event("input", { bubbles: true })),
    );
  }
  await act(async () =>
    container
      .querySelector("form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      ),
  );
  assert.deepEqual(request, [
    "register",
    "expert-review",
    "long-test-password",
  ]);
});

test("keyboard suggestion selection preserves the original query and signed generation", async () => {
  let request;
  const state = {
    query: "команда",
    kind: "course",
    suggestions: [
      {
        id: "signed-choice",
        selection_generation: "g1",
        label: "Команда",
        entity_key: "course:1",
      },
    ],
    relatedTopics: [],
    suggestOpen: true,
    setSuggestOpen: () => {},
    setQuery: () => {},
  };
  await act(async () =>
    root.render(
      <SearchBar
        state={state}
        onSearch={(...args) => {
          request = args;
        }}
      />,
    ),
  );
  const input = container.querySelector("input");
  await act(async () =>
    input.dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    ),
  );
  await act(async () =>
    input.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  assert.deepEqual(request, [
    "команда",
    "course",
    { selection: { id: "signed-choice", generation: "g1" } },
  ]);
});

test("the whole material card opens the actual item without inventing unknown price", async () => {
  let opened;
  await act(async () =>
    root.render(
      <MaterialCard
        item={item}
        onView={(value) => {
          opened = value;
        }}
      />,
    ),
  );
  await click(container.querySelector(".card-open"));
  assert.equal(opened, item);
  assert.doesNotMatch(container.textContent, /Бесплатно|₽/);
});

test("material dialog traps Tab, closes on Escape and restores focus and body scroll", async () => {
  let closes = 0;
  const previous = document.querySelector("#previous");
  previous.focus();
  await act(async () => {
    root.render(
      <MaterialDialog
        item={item}
        onClose={() => {
          closes++;
        }}
        onComplete={() => {}}
        onStarted={() => {}}
      />,
    );
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
  const buttons = container.querySelectorAll("button");
  assert.equal(document.body.style.overflow, "hidden");
  buttons[buttons.length - 1].focus();
  await act(async () =>
    document.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "Tab",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  assert.equal(document.activeElement, buttons[0]);
  await act(async () =>
    document.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  assert.equal(closes, 1);
  await act(async () => root.render(null));
  assert.equal(document.activeElement, previous);
  assert.equal(document.body.style.overflow, "");
});

test("onboarding saves an empty optional goal as null and prevents double submission", async () => {
  let submitted, finish;
  await act(async () =>
    root.render(
      <Onboarding
        initial={{ categories: ["business"], goal: "" }}
        onClose={() => {}}
        onFinish={(value) => {
          submitted = value;
          return new Promise((resolve) => {
            finish = resolve;
          });
        }}
      />,
    ),
  );
  await click(
    [...container.querySelectorAll("button")].find((button) =>
      button.textContent.includes("Продолжить"),
    ),
  );
  await act(async () =>
    container
      .querySelector("form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      ),
  );
  assert.deepEqual(submitted, { categories: ["business"], goal: null });
  assert.equal(container.querySelector('button[type="submit"]').disabled, true);
  await act(async () => finish());
});

test("mobile navigation closes on Escape and returns focus without trapping the page", async () => {
  const { Workspace } = await import("../src/app/Workspace.jsx");
  function Harness() {
    const [mobileMenu, setMobileMenu] = React.useState(false);
    return (
      <Workspace
        auth={{ username: "reviewer" }}
        tab="search"
        navigate={() => setMobileMenu(false)}
        mobileMenu={mobileMenu}
        setMobileMenu={setMobileMenu}
        search={{
          query: "",
          submitted: "",
          suggestions: [],
          relatedTopics: [],
          setSuggestOpen: () => {},
        }}
        catalog={{ loaded: true, items: [], total: 0, kind: "" }}
        profileState={{
          profile: { categories: [] },
          viewed: [],
          completed: [],
        }}
        profileReady
        generation="fixture"
        setOnboarding={() => {}}
        runSearch={() => {}}
        logout={() => {}}
      />
    );
  }
  await act(async () => root.render(<Harness />));
  const trigger = container.querySelector('[aria-label="Открыть меню"]');
  trigger.focus();
  await click(trigger);
  assert.equal(
    container
      .querySelector('[aria-controls="main-navigation"]')
      .getAttribute("aria-expanded"),
    "true",
  );
  assert.equal(container.querySelector("main").hasAttribute("inert"), true);
  assert.equal(document.body.style.overflow, "hidden");
  await act(async () =>
    document.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  assert.equal(
    container
      .querySelector('[aria-controls="main-navigation"]')
      .getAttribute("aria-expanded"),
    "false",
  );
  assert.equal(document.body.style.overflow, "");
  assert.equal(document.activeElement, trigger);
});
