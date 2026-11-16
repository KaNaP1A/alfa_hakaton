import React, { useState } from "react";
import {
  ArrowRight,
  Search,
  SlidersHorizontal,
  Route,
  Eye,
  EyeOff,
  ArrowUpRight,
  LoaderCircle,
} from "lucide-react";
import { Brand } from "../../shared/ui/Brand.jsx";

export function AuthScreen({ auth }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");
  const busy = auth.status === "loading";
  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      await auth.authenticate(mode, username.trim(), password);
    } catch (failure) {
      setError(
        failure.status === 401
          ? "Проверьте логин и пароль."
          : failure.status === 409
            ? "Этот логин уже занят. Выберите другой."
            : failure.status === 503
              ? "Сервис временно недоступен. Попробуйте войти позже."
              : failure.message,
      );
    }
  }
  function changeMode(next) {
    setMode(next);
    setError("");
    auth.clearError?.();
  }
  return (
    <div className="auth-page">
      <header className="site-header">
        <div className="shell wrap header-inner">
          <a className="skip-link" href="#main">
            К содержимому
          </a>
          <Brand />
          <a
            className="reference-link"
            href="https://kurs.alfabank.ru/"
            target="_blank"
            rel="noreferrer"
          >
            Об Альфа-Курсе <ArrowUpRight size={16} />
          </a>
        </div>
      </header>
      <main id="main" className="auth-main">
        <section className="auth-hero hero" data-enter="">
          <div className="shell wrap auth-grid">
            <div className="auth-story">
              <span className="product-label">
                <span className="red-dot" /> Обучение для предпринимателей
              </span>
              <h1>
                Знания для
                <br /> вашего бизнеса
              </h1>
              <p className="auth-lead">
                От первой идеи до новых точек роста.
                <br className="desktop-break" /> Находите обучение под задачи
                своего дела.
              </p>
              <div className="auth-features">
                <div>
                  <Search />
                  <span>
                    <strong>Найдите решение</strong>
                    <span>Опишите задачу своими словами</span>
                  </span>
                </div>
                <div>
                  <SlidersHorizontal />
                  <span>
                    <strong>Выберите своё</strong>
                    <span>Получите подборку по интересам</span>
                  </span>
                </div>
                <div>
                  <Route />
                  <span>
                    <strong>Сделайте следующий шаг</strong>
                    <span>Соберите маршрут по изученным темам</span>
                  </span>
                </div>
              </div>
              <div className="auth-preview" aria-hidden="true">
                <div className="auth-preview-step">
                  <span className="auth-preview-icon"><Search size={18} /></span>
                  <span>Задача</span>
                </div>
                <span className="auth-preview-connector" />
                <div className="auth-preview-step">
                  <span className="auth-preview-icon"><SlidersHorizontal size={18} /></span>
                  <span>Подборка</span>
                </div>
                <span className="auth-preview-connector" />
                <div className="auth-preview-step">
                  <span className="auth-preview-icon"><Route size={18} /></span>
                  <span>Маршрут</span>
                </div>
              </div>
              <p className="prototype-note">
                6 форматов материалов в одном каталоге
              </p>
            </div>
            <div
              className="auth-panel"
              role="region"
              aria-labelledby="auth-title"
            >
              <div className="auth-tabs" aria-label="Вход в аккаунт">
                <button
                  type="button"
                  className={mode === "login" ? "active" : ""}
                  aria-pressed={mode === "login"}
                  onClick={() => changeMode("login")}
                >
                  Вход
                </button>
                <button
                  type="button"
                  className={mode === "register" ? "active" : ""}
                  aria-pressed={mode === "register"}
                  onClick={() => changeMode("register")}
                >
                  Регистрация
                </button>
              </div>
              <h2 id="auth-title">
                {mode === "login" ? "С возвращением" : "Начнём знакомство"}
              </h2>
              <p className="auth-intro">
                {mode === "login"
                  ? "Войдите, чтобы продолжить обучение и найти новые материалы."
                  : "Сохраните интересы и получайте персональные рекомендации."}
              </p>
              <form onSubmit={submit} className="auth-form">
                <label htmlFor="username">
                  Логин
                  <span className="input-wrap">
                    <input
                      id="username"
                      name="username"
                      autoComplete="username"
                      placeholder="Ваш логин"
                      pattern={"[A-Za-z0-9_.\\-]{3,64}"}
                      title="От 3 до 64 символов: латиница, цифры, точка, дефис или подчёркивание"
                      minLength={3}
                      maxLength={64}
                      required
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                    />
                  </span>
                </label>
                <label htmlFor="password">
                  Пароль
                  <span className="input-wrap password-wrap">
                    <input
                      id="password"
                      name="password"
                      type={visible ? "text" : "password"}
                      placeholder={
                        mode === "register"
                          ? "Не менее 10 символов"
                          : "Ваш пароль"
                      }
                      autoComplete={
                        mode === "login" ? "current-password" : "new-password"
                      }
                      minLength={10}
                      maxLength={128}
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                    <button
                      className="icon-button"
                      type="button"
                      onClick={() => setVisible((v) => !v)}
                      aria-label={visible ? "Скрыть пароль" : "Показать пароль"}
                    >
                      {visible ? <EyeOff size={20} /> : <Eye size={20} />}
                    </button>
                  </span>
                </label>
                {mode === "register" && (
                  <p className="field-help">
                    Логин — латиницей, от 3 символов. Используйте отдельный
                    пароль для этого прототипа.
                  </p>
                )}
                {(error || auth.error) && (
                  <p className="notice" role="alert">
                    {error || auth.error}
                  </p>
                )}
                <button
                  className="primary btn btn--primary auth-submit"
                  type="submit"
                  disabled={busy}
                >
                  {busy ? (
                    <>
                      <LoaderCircle size={18} className="spin" />
                      Подключаемся
                    </>
                  ) : (
                    <>
                      {mode === "login" ? "Войти в аккаунт" : "Создать аккаунт"}
                      <ArrowRight size={18} />
                    </>
                  )}
                </button>
              </form>
              <p className="auth-fineprint">
                Учебный прототип. Аккаунт создаётся отдельно
                <br className="desktop-break" /> от личного кабинета на сайте
                Альфа-Курса.
              </p>
            </div>
          </div>
        </section>
      </main>
      <footer className="auth-footer">
        <div className="shell wrap auth-footer-inner">
          <span>Альфа-Курс</span>
          <span>Обучение для бизнеса</span>
        </div>
      </footer>
    </div>
  );
}
