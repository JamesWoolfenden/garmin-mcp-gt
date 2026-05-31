# Creates the full fuel-pwa UI structure in E:\Code\garmin\ui
# Run from anywhere.

$UI = "E:\Code\garmin\ui"

$UTF8NoBOM = New-Object System.Text.UTF8Encoding $false

function Write-File {
    param($Path, $Content)
    $full = Join-Path $UI $Path
    $dir = Split-Path $full
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [IO.File]::WriteAllText($full, $Content, $UTF8NoBOM)
    Write-Host "   $Path"
}

Write-Host "-> Scaffolding $UI..."

Write-File "package.json" @'
{
  "name": "fuel-pwa",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test"
  },
  "browserslist": {
    "production": [">0.2%", "not dead", "not op_mini all"],
    "development": ["last 1 chrome version", "last 1 firefox version", "last 1 safari version"]
  }
}
'@

Write-File "public/manifest.json" @'
{
  "short_name": "Fuel",
  "name": "Fuel — Activity & Food Tracker",
  "icons": [
    { "src": "icons/icon-192.png", "type": "image/png", "sizes": "192x192", "purpose": "any maskable" },
    { "src": "icons/icon-512.png", "type": "image/png", "sizes": "512x512", "purpose": "any maskable" }
  ],
  "start_url": ".",
  "display": "standalone",
  "theme_color": "#0f172a",
  "background_color": "#0f172a",
  "description": "Log food, track activity, get nudged to move."
}
'@

Write-File "public/index.html" @'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#0f172a" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="Fuel" />
  <link rel="manifest" href="%PUBLIC_URL%/manifest.json" />
  <link rel="apple-touch-icon" href="%PUBLIC_URL%/icons/icon-192.png" />
  <title>Fuel</title>
</head>
<body>
  <noscript>You need to enable JavaScript to run this app.</noscript>
  <div id="root"></div>
</body>
</html>
'@

Write-File "public/sw.js" @'
const CACHE_NAME = "fuel-v1";
const STATIC_ASSETS = ["/", "/index.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(clients.claim());
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

self.addEventListener("push", (e) => {
  if (!e.data) return;
  const data = e.data.json();
  e.waitUntil(
    self.registration.showNotification(data.title || "Fuel", {
      body: data.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: data.tag || "fuel-nudge",
      data: { url: data.url || "/" }
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => {
      const existing = cs.find(c => c.url.includes(self.location.origin));
      if (existing) return existing.focus();
      return clients.openWindow(e.notification.data?.url || "/");
    })
  );
});
'@

Write-File "src/index.js" @'
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<React.StrictMode><App /></React.StrictMode>);
'@

Write-File "src/lib/api.js" @'
const BASE = process.env.REACT_APP_API_URL || "";

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const logFood      = (text) => req("/food", { method: "POST", body: JSON.stringify({ text }) });
export const getTodayFood = ()     => req("/food/today");
export const deleteFood   = (id)   => req(`/food/${id}`, { method: "DELETE" });
export const getBalance   = ()     => req("/balance");
export const getProfile   = ()     => req("/profile");
export const updateProfile = (d)   => req("/profile", { method: "PUT", body: JSON.stringify(d) });

export async function subscribePush(subscription) {
  return req("/push/subscribe", { method: "POST", body: JSON.stringify(subscription) });
}
export async function unsubscribePush(endpoint) {
  return req("/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint }) });
}
'@

Write-File "src/hooks/usePush.js" @'
import { useState, useEffect, useCallback } from "react";
import { subscribePush, unsubscribePush } from "../lib/api";

const VAPID_PUBLIC_KEY = process.env.REACT_APP_VAPID_PUBLIC_KEY || "";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

export function usePush() {
  const [state, setState] = useState("idle");
  const [subscription, setSubscription] = useState(null);

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setState("unsupported"); return;
    }
    navigator.serviceWorker.register("/sw.js").then(reg => {
      reg.pushManager.getSubscription().then(sub => {
        if (sub) { setSubscription(sub); setState("subscribed"); }
        else setState("idle");
      });
    });
  }, []);

  const subscribe = useCallback(async () => {
    try {
      setState("loading");
      const reg = await navigator.serviceWorker.ready;
      const permission = await Notification.requestPermission();
      if (permission !== "granted") { setState("denied"); return; }
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
      });
      await subscribePush(sub.toJSON());
      setSubscription(sub);
      setState("subscribed");
    } catch (err) {
      console.error("Push subscribe failed:", err);
      setState("error");
    }
  }, []);

  const unsubscribe = useCallback(async () => {
    if (!subscription) return;
    try {
      await unsubscribePush(subscription.endpoint);
      await subscription.unsubscribe();
      setSubscription(null);
      setState("idle");
    } catch (err) {
      console.error("Push unsubscribe failed:", err);
    }
  }, [subscription]);

  return { state, subscription, subscribe, unsubscribe };
}
'@

Write-File "src/App.js" @'
import React, { useState, useEffect, useRef, useCallback } from "react";
import { logFood, getTodayFood, deleteFood, getBalance } from "./lib/api";
import { usePush } from "./hooks/usePush";
import "./App.css";

function BalanceBar({ kcalIn, kcalBurned, kcalTarget }) {
  const net = kcalIn - kcalBurned;
  const pct = Math.min(100, Math.round((net / kcalTarget) * 100));
  const over = net > kcalTarget;
  return (
    <div className="balance-bar-wrap">
      <div className="balance-numbers">
        <span className="balance-num">
          <span className="num">{Math.round(kcalIn)}</span>
          <span className="lbl">in</span>
        </span>
        <span className="balance-minus">−</span>
        <span className="balance-num">
          <span className="num">{Math.round(kcalBurned)}</span>
          <span className="lbl">burned</span>
        </span>
        <span className="balance-minus">=</span>
        <span className={`balance-num ${over ? "over" : "ok"}`}>
          <span className="num">{Math.round(net)}</span>
          <span className="lbl">net / {Math.round(kcalTarget)} target</span>
        </span>
      </div>
      <div className="track">
        <div className={`fill ${over ? "over" : ""}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FoodEntry({ entry, onDelete }) {
  return (
    <div className="food-entry">
      <div className="food-entry-left">
        <span className="food-parsed">{entry.parsed}</span>
        <span className="food-time">
          {new Date(entry.logged_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
      <div className="food-entry-right">
        <span className="food-kcal">{Math.round(entry.kcal)} kcal</span>
        <button className="delete-btn" onClick={() => onDelete(entry.id)} aria-label="Remove">×</button>
      </div>
    </div>
  );
}

function Recommendation({ text, status }) {
  if (!text) return null;
  const icon = status === "on_track" ? "✓" : status === "over" ? "↑" : "↓";
  return (
    <div className={`rec rec-${status}`}>
      <span className="rec-icon">{icon}</span>
      <span className="rec-text">{text}</span>
    </div>
  );
}

function PushToggle({ pushState, onSubscribe, onUnsubscribe }) {
  if (pushState === "unsupported") return null;
  if (pushState === "subscribed")
    return <button className="push-btn active" onClick={onUnsubscribe}>Nudges on</button>;
  return (
    <button className="push-btn" onClick={onSubscribe} disabled={pushState === "loading"}>
      {pushState === "loading" ? "Enabling…" : "Enable nudges"}
    </button>
  );
}

export default function App() {
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState([]);
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const { state: pushState, subscribe, unsubscribe } = usePush();

  const loadData = useCallback(async () => {
    try {
      const [food, bal] = await Promise.all([getTodayFood(), getBalance()]);
      setEntries(food.entries);
      setBalance(bal);
    } catch (e) {
      setError("Could not load data");
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleLog = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const entry = await logFood(input.trim());
      setEntries(prev => [entry, ...prev]);
      setInput("");
      const bal = await getBalance();
      setBalance(bal);
    } catch (e) {
      setError("Failed to log — try again");
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteFood(id);
      setEntries(prev => prev.filter(e => e.id !== id));
      const bal = await getBalance();
      setBalance(bal);
    } catch (e) {
      setError("Could not remove entry");
    }
  };

  const totalKcal = entries.reduce((s, e) => s + e.kcal, 0);

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <span className="wordmark">fuel</span>
          <PushToggle pushState={pushState} onSubscribe={subscribe} onUnsubscribe={unsubscribe} />
        </div>
      </header>

      {balance && (
        <div className="balance-section">
          <BalanceBar kcalIn={balance.kcal_in} kcalBurned={balance.kcal_burned} kcalTarget={balance.kcal_target} />
          <Recommendation text={balance.recommendation} status={balance.status} />
        </div>
      )}

      <form className="log-form" onSubmit={handleLog}>
        <input
          ref={inputRef}
          className="log-input"
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="had granola and a coffee…"
          disabled={loading}
          autoComplete="off"
          autoCapitalize="none"
        />
        <button className="log-btn" type="submit" disabled={loading || !input.trim()}>
          {loading ? "…" : "Log"}
        </button>
      </form>

      {error && <div className="error-banner">{error}</div>}

      <div className="entries">
        {entries.length === 0 && (
          <p className="empty">Nothing logged yet. Tell me what you have eaten.</p>
        )}
        {entries.map(entry => (
          <FoodEntry key={entry.id} entry={entry} onDelete={handleDelete} />
        ))}
      </div>

      {entries.length > 0 && (
        <div className="day-total">
          <span>Total today</span>
          <span>{Math.round(totalKcal)} kcal</span>
        </div>
      )}
    </div>
  );
}
'@

Write-File "src/App.css" @'
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0f172a; --surface: #1e293b; --surface2: #334155; --border: #334155;
  --text: #f1f5f9; --muted: #94a3b8; --accent: #38bdf8; --accent-dim: rgba(56,189,248,0.12);
  --over: #f87171; --over-dim: rgba(248,113,113,0.12); --ok: #4ade80; --ok-dim: rgba(74,222,128,0.1);
  --radius: 10px; --font: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
html, body, #root { height: 100%; background: var(--bg); }
body { font-family: var(--font); color: var(--text); -webkit-font-smoothing: antialiased; overscroll-behavior: none; }
.app { max-width: 480px; margin: 0 auto; min-height: 100dvh; display: flex; flex-direction: column; padding-bottom: env(safe-area-inset-bottom, 24px); }
.header { padding: 16px 20px 12px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--bg); z-index: 10; }
.header-inner { display: flex; align-items: center; justify-content: space-between; }
.wordmark { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; color: var(--accent); }
.push-btn { font-size: 12px; padding: 6px 12px; border-radius: 20px; border: 1px solid var(--border); background: transparent; color: var(--muted); cursor: pointer; transition: all 0.15s; }
.push-btn:hover { border-color: var(--accent); color: var(--accent); }
.push-btn.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.balance-section { padding: 16px 20px 0; }
.balance-bar-wrap { margin-bottom: 12px; }
.balance-numbers { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.balance-num { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.balance-num .num { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text); }
.balance-num .lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }
.balance-num.over .num { color: var(--over); }
.balance-num.ok .num { color: var(--ok); }
.balance-minus { color: var(--muted); font-size: 16px; padding-bottom: 16px; }
.track { height: 4px; background: var(--surface2); border-radius: 2px; overflow: hidden; }
.fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.4s ease; }
.fill.over { background: var(--over); }
.rec { display: flex; align-items: flex-start; gap: 8px; padding: 10px 14px; border-radius: var(--radius); margin-bottom: 4px; font-size: 14px; line-height: 1.5; }
.rec-on_track { background: var(--ok-dim); }
.rec-over { background: var(--over-dim); }
.rec-under { background: var(--accent-dim); }
.rec-icon { font-size: 14px; margin-top: 1px; flex-shrink: 0; }
.rec-text { color: var(--text); }
.log-form { display: flex; gap: 8px; padding: 16px 20px; position: sticky; bottom: 0; background: var(--bg); border-top: 1px solid var(--border); margin-top: auto; }
.log-input { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; color: var(--text); font-size: 16px; font-family: var(--font); outline: none; transition: border-color 0.15s; min-width: 0; }
.log-input:focus { border-color: var(--accent); }
.log-input::placeholder { color: var(--muted); }
.log-btn { background: var(--accent); color: #0f172a; border: none; border-radius: var(--radius); padding: 12px 18px; font-size: 15px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; white-space: nowrap; }
.log-btn:disabled { opacity: 0.4; cursor: default; }
.log-btn:not(:disabled):hover { opacity: 0.85; }
.error-banner { margin: 0 20px 8px; padding: 10px 14px; background: var(--over-dim); border: 1px solid var(--over); border-radius: var(--radius); font-size: 13px; color: var(--over); }
.entries { flex: 1; padding: 8px 20px; overflow-y: auto; }
.empty { color: var(--muted); font-size: 14px; text-align: center; padding: 40px 0; line-height: 1.6; }
.food-entry { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.food-entry:last-child { border-bottom: none; }
.food-entry-left { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.food-parsed { font-size: 14px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.food-time { font-size: 12px; color: var(--muted); }
.food-entry-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.food-kcal { font-size: 14px; font-weight: 500; color: var(--accent); font-variant-numeric: tabular-nums; }
.delete-btn { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 2px 4px; line-height: 1; transition: color 0.15s; }
.delete-btn:hover { color: var(--over); }
.day-total { display: flex; justify-content: space-between; padding: 12px 20px; border-top: 1px solid var(--border); font-size: 13px; color: var(--muted); font-weight: 500; }
.day-total span:last-child { color: var(--text); }
'@

Write-File "firebase.json" @'
{
  "hosting": {
    "public": "build",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [{ "source": "**", "destination": "/index.html" }],
    "headers": [
      {
        "source": "/sw.js",
        "headers": [
          { "key": "Cache-Control", "value": "no-cache" },
          { "key": "Service-Worker-Allowed", "value": "/" }
        ]
      }
    ]
  }
}
'@

Write-File ".env.example" @'
REACT_APP_API_URL=https://fuel-backend-zbq7wtzkjq-ew.a.run.app
REACT_APP_VAPID_PUBLIC_KEY=your_vapid_public_key_here
'@

Write-Host ""
Write-Host "Done. All files written to $UI"
Write-Host "Now run: cd $UI && ..\backend\setup_firebase.ps1"