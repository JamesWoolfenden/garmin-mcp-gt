import { getIdToken } from "../firebase";

const BASE = import.meta.env.VITE_API_URL || "";

async function req(path, opts = {}) {
  const token = await getIdToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
    ...opts,
  });
  if (res.status === 403) {
    // Sign out and surface a clear message rather than leaving a broken state
    const { signOutUser } = await import("../firebase");
    await signOutUser();
    throw new Error("ACCESS_DENIED");
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const logFood      = (text) => req("/food", { method: "POST", body: JSON.stringify({ text }) });
export const getTodayFood = ()     => req("/food/today");
export const deleteFood   = (id)   => req(`/food/${id}`, { method: "DELETE" });
export const getBalance   = (date) => req(date ? `/balance?date=${date}` : "/balance");
export const getProfile   = ()     => req("/profile");
export const updateProfile = (d)   => req("/profile", { method: "PUT", body: JSON.stringify(d) });

export async function subscribePush(subscription) {
  return req("/push/subscribe", { method: "POST", body: JSON.stringify(subscription) });
}
export async function unsubscribePush(endpoint) {
  return req("/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint }) });
}
export const sendChat = (message, history = []) => req("/chat", {
  method: "POST",
  body: JSON.stringify({ message, history }),
});
export const getChatHistory = () => req("/chat/history");
export const createGarminUploadToken = () => req("/garmin/upload-token", { method: "POST" });
