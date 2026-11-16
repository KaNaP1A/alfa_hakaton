import { useEffect, useState } from "react";
import { api, setAccessToken, onUnauthorized } from "../../shared/api/index.js";
const TOKEN_KEY = "alfa_api_session_token";
export function useAuth() {
  const [token, setToken] = useState(() => {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return "";
    }
  });
  const [status, setStatus] = useState(token ? "checking" : "guest");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setAccessToken(token);
    onUnauthorized(clear);
    if (!token) {
      setStatus("guest");
      return;
    }
    let cancelled = false;
    api
      .me()
      .then((user) => {
        if (!cancelled) {
          setUsername(user.username);
          setStatus("authenticated");
        }
      })
      .catch(() => {
        if (!cancelled) clear();
      });
    return () => {
      cancelled = true;
    };
  }, [token]);
  function clear() {
    setAccessToken("");
    setToken("");
    setUsername("");
    setStatus("guest");
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {}
  }
  async function authenticate(type, login, password) {
    setError("");
    setStatus("loading");
    try {
      const result =
        type === "register"
          ? await api.register(login, password)
          : await api.login(login, password);
      setAccessToken(result.access_token);
      try {
        sessionStorage.setItem(TOKEN_KEY, result.access_token);
      } catch {}
      setToken(result.access_token);
      setUsername(login);
      setStatus("authenticated");
    } catch (e) {
      setStatus("guest");
      setError(e.userMessage||e.message);
      throw e;
    }
  }
  async function logout() {
    try {
      await api.logout();
    } finally {
      clear();
    }
  }
  return {
    status,
    username,
    error,
    clearError: () => setError(""),
    authenticate,
    logout,
    clear,
    authenticated: status === "authenticated",
  };
}
