import React, { useState, useEffect, useRef, useCallback } from "react";
import { logFood, getTodayFood, deleteFood, getBalance } from "./lib/api";
import { usePush } from "./hooks/usePush";
import { useAuth } from "./hooks/useAuth";
import { signInWithGoogle, signInWithEmail, registerWithEmail, signOutUser } from "./firebase";
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
  if (pushState === "denied")
    return <span className="push-err">Notifications blocked — check browser settings</span>;
  if (pushState.startsWith("error:"))
    return <span className="push-err" title={pushState.slice(6)}>Nudge setup failed</span>;
  return (
    <button className="push-btn" onClick={onSubscribe} disabled={pushState === "loading"}>
      {pushState === "loading" ? "Enabling…" : "Enable nudges"}
    </button>
  );
}

function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("signin"); // signin | register
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleEmail = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "register") await registerWithEmail(email, password);
      else await signInWithEmail(email, password);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="signin">
      <h1 className="wordmark">fuel</h1>
      <button className="google-btn" onClick={() => signInWithGoogle().catch(e => setError(e.message))}>
        Sign in with Google
      </button>
      <div className="divider">or</div>
      <form onSubmit={handleEmail}>
        <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
        <button type="submit" disabled={loading}>{mode === "register" ? "Register" : "Sign in"}</button>
      </form>
      <button className="link-btn" onClick={() => setMode(mode === "signin" ? "register" : "signin")}>
        {mode === "signin" ? "Create an account" : "Already have an account?"}
      </button>
      {error && <p className="error-banner">{error}</p>}
    </div>
  );
}

export default function App() {
  const user = useAuth();
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

  useEffect(() => { if (user) loadData(); }, [loadData, user]);

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

  if (user === undefined) return <div className="app"><p style={{padding:"2rem"}}>Loading…</p></div>;
  if (user === null) return <SignIn />;

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <span className="wordmark">fuel</span>
          <div style={{display:"flex",gap:"0.5rem",alignItems:"center"}}>
            <PushToggle pushState={pushState} onSubscribe={subscribe} onUnsubscribe={unsubscribe} />
            <button className="push-btn" onClick={signOutUser}>Sign out</button>
          </div>
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