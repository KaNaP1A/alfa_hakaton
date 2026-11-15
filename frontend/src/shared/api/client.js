/** Public FastAPI adapter: backend/api/routes.py (not the internal ML protocol). */
const PREFIX = "/api/v1";
const TIMEOUT = 30000;
let accessToken = "";
let unauthorizedHandler = null;
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}
export function setAccessToken(token) {
  accessToken = token || "";
}
export class ApiError extends Error {
  constructor(message, status = 0, code = "", details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.userMessage =
      {
        0: "Сервер приложения не отвечает. Запустите `sh ./run.sh` в корне проекта и повторите.",
        400: "Измените запрос и попробуйте ещё раз.",
        401: "Сессия завершилась. Войдите в аккаунт снова.",
        404: "Материал пока недоступен. Вернитесь к каталогу.",
        409: "Данные обновились. Обновите страницу и повторите.",
        422: "Проверьте заполненные поля.",
        429: "Слишком много запросов. Подождите немного и повторите.",
        500: "Сервис временно недоступен. Попробуйте позже.",
        502: "Не удалось получить материалы. Попробуйте ещё раз.",
        503: "Сервис временно недоступен. Попробуйте позже.",
        504: "Подбор занял больше времени, чем обычно. Повторите запрос.",
      }[status] || message;
    this.details = details;
  }
}
async function request(
  path,
  { method = "GET", body, signal, authenticated = true } = {},
) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(() => controller.abort(), TIMEOUT);
  try {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (authenticated && accessToken)
      headers.Authorization = `Bearer ${accessToken}`;
    const response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (response.status === 204) return null;
    let data;
    try {
      data = await response.json();
    } catch {
      throw new ApiError("Сервер вернул некорректный ответ.", response.status);
    }
    if (!response.ok) {
      if (response.status === 401 && authenticated && accessToken)
        unauthorizedHandler?.();
      throw new ApiError(
        data?.error?.message || `HTTP ${response.status}`,
        response.status,
        data?.error?.code || "",
        data?.error?.details,
      );
    }
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e?.name === "AbortError") {
      if (signal?.aborted) throw e;
      throw new ApiError("Превышено время ожидания ответа.", 504, "timeout");
    }
    throw new ApiError("Не удалось связаться с сервером.", 0, "network");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
const params = (values) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  }
  return q.toString();
};
const checkQuery = (q) => {
  const s = String(q ?? "").trim();
  if (!s || s.length > 300)
    throw new ApiError("Запрос должен содержать от 1 до 300 символов.");
  return s;
};
export const api = {
  health(signal) {
    return request("/health", { signal, authenticated: false });
  },
  ready(signal) {
    return request("/ready", { signal, authenticated: false });
  },
  register(username, password) {
    return request(`${PREFIX}/auth/register`, {
      method: "POST",
      body: { username, password },
      authenticated: false,
    });
  },
  login(username, password) {
    return request(`${PREFIX}/auth/login`, {
      method: "POST",
      body: { username, password },
      authenticated: false,
    });
  },
  logout() {
    return request(`${PREFIX}/auth/logout`, { method: "POST" });
  },
  me(signal) {
    return request(`${PREFIX}/me`, { signal });
  },
  updateProfile(profile, signal) {
    return request(`${PREFIX}/me/profile`, {
      method: "PUT",
      body: profile,
      signal,
    });
  },
  events(limit = 50, signal) {
    return request(`${PREFIX}/me/events?${params({ limit })}`, { signal });
  },
  addEvent({ generation, event_id, entity_key, action, position = null }) {
    return request(`${PREFIX}/me/events`, {
      method: "POST",
      body: { generation, event_id, entity_key, action, position },
    });
  },
  catalog({ q = "", kind = "", limit = 20, offset = 0 } = {}, signal) {
    return request(`${PREFIX}/catalog?${params({ q, kind, limit, offset })}`, {
      signal,
    });
  },
  suggest(q, signal) {
    return request(
      `${PREFIX}/suggest?${params({
        q: String(q ?? "")
          .trim()
          .slice(0, 300),
        limit: 6,
      })}`,
      { signal },
    );
  },
  search({ q, kind = "", selection, clarification, signal, top = 12 }) {
    const data = { q: checkQuery(q), kind, top };
    if (selection && clarification)
      throw new ApiError("Выберите подсказку или уточнение.");
    if (selection) {
      if (!selection.id || !selection.generation)
        throw new ApiError("Устаревшая подсказка.");
      data.selection_id = selection.id;
      data.selection_generation = selection.generation;
    }
    if (clarification) {
      if (clarification.token) data.clarification_token = clarification.token;
      else if (clarification.text?.trim())
        data.clarification_text = clarification.text.trim().slice(0, 100);
    }
    return request(`${PREFIX}/search?${params(data)}`, { signal });
  },
  recommend({ generation }, signal) {
    return request(`${PREFIX}/recommend`, {
      method: "POST",
      body: { generation },
      signal,
    });
  },
  developmentPlan({ generation }, signal) {
    return request(`${PREFIX}/development-plan`, {
      method: "POST",
      body: { generation },
      signal,
    });
  },
};
