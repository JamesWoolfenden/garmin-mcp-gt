import React, { useState, useEffect, useRef, useCallback } from "react";
import { logFood, deleteFood, getBalance, sendChat, createGarminUploadToken, getProfile, updateProfile } from "./lib/api";
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

function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", text }]);
    setLoading(true);
    try {
      const { response } = await sendChat(text);
      setMessages(prev => [...prev, { role: "assistant", text: response }]);
    } catch {
      setMessages(prev => [...prev, { role: "assistant", text: "Sorry, something went wrong." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat">
      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="empty">Ask about your activity, sleep, heart rate…</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-msg-${m.role}`}>{m.text}</div>
        ))}
        {loading && <div className="chat-msg chat-msg-assistant">…</div>}
        <div ref={bottomRef} />
      </div>
      <form className="log-form" onSubmit={send}>
        <input
          className="log-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="How did I sleep last night?"
          disabled={loading}
          autoComplete="off"
        />
        <button className="log-btn" type="submit" disabled={loading || !input.trim()}>Ask</button>
      </form>
    </div>
  );
}

function Settings() {
  const [kcalTarget, setKcalTarget] = useState("");
  const [nudgeTimes, setNudgeTimes] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getProfile().then(p => {
      if (cancelled) return;
      setKcalTarget(String(p.kcal_target || 2000));
      setNudgeTimes((p.nudge_times || []).join(", "));
      setSaved({ kcal_target: p.kcal_target, nudge_times: p.nudge_times });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const save = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const times = nudgeTimes.split(",").map(t => t.trim()).filter(Boolean);
      await updateProfile({ kcal_target: parseInt(kcalTarget), nudge_times: times });
      setSaved({ kcal_target: parseInt(kcalTarget), nudge_times: times });
      setOpen(false);
    } catch {
      // leave open on error
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{padding:"16px 20px",borderTop:"1px solid var(--border)"}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div>
          <p style={{fontSize:"13px",color:"var(--muted)",fontWeight:500}}>Settings</p>
          {saved && !open && (
            <p style={{fontSize:"12px",color:"var(--muted)",marginTop:"2px"}}>
              {saved.kcal_target} kcal · nudges {(saved.nudge_times || []).join(", ")}
            </p>
          )}
        </div>
        <button className="push-btn" onClick={() => setOpen(o => !o)}>
          {open ? "Cancel" : "Edit"}
        </button>
      </div>
      {open && (
        <form onSubmit={save} style={{display:"flex",flexDirection:"column",gap:"10px",marginTop:"12px"}}>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Daily kcal target
            <input
              className="log-input"
              type="number"
              value={kcalTarget}
              onChange={e => setKcalTarget(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}}
              min="500" max="6000"
            />
          </label>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Nudge times (comma-separated)
            <input
              className="log-input"
              type="text"
              value={nudgeTimes}
              onChange={e => setNudgeTimes(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}}
              placeholder="08:00, 13:00, 15:00, 20:00"
            />
          </label>
          <button className="log-btn" type="submit" disabled={loading}>
            {loading ? "Saving…" : "Save"}
          </button>
        </form>
      )}
    </div>
  );
}

function GarminConnect() {
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    setLoading(true);
    try {
      const { token: t } = await createGarminUploadToken();
      setToken(t);
    } finally {
      setLoading(false);
    }
  };

  const copy = () => {
    navigator.clipboard.writeText(
      `cd E:\\code\\garmin && .\\garmin-upload-tokens.ps1 -UploadToken "${token}"`
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{padding:"16px 20px",borderTop:"1px solid var(--border)"}}>
      <p style={{fontSize:"13px",color:"var(--muted)",marginBottom:"10px"}}>
        Connect your Garmin to enable activity-aware advice.
      </p>
      {!token ? (
        <button className="push-btn" onClick={generate} disabled={loading}>
          {loading ? "Generating…" : "Connect Garmin"}
        </button>
      ) : (
        <div>
          <p style={{fontSize:"12px",color:"var(--muted)",marginBottom:"6px"}}>
            Run this command on your desktop (valid 15 min):
          </p>
          <code style={{fontSize:"11px",background:"var(--surface)",padding:"8px",borderRadius:"6px",display:"block",wordBreak:"break-all",color:"var(--accent)"}}>
            .\garmin-upload-tokens.ps1 -UploadToken "{token}"
          </code>
          <button className="push-btn" style={{marginTop:"8px"}} onClick={copy}>
            {copied ? "Copied!" : "Copy command"}
          </button>
        </div>
      )}
    </div>
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
  const [tab, setTab] = useState("food"); // food | chat
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState([]);
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const { state: pushState, subscribe, unsubscribe } = usePush();

  const loadData = useCallback(async () => {
    try {
      const bal = await getBalance();
      setEntries(bal.entries || []);
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
      await logFood(input.trim());
      setInput("");
      const bal = await getBalance();
      setEntries(bal.entries || []);
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
      const bal = await getBalance();
      setEntries(bal.entries || []);
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
            <button className={`push-btn${tab === "food" ? " active" : ""}`} onClick={() => setTab("food")}>Log</button>
            <button className={`push-btn${tab === "chat" ? " active" : ""}`} onClick={() => setTab("chat")}>Ask</button>
            <PushToggle pushState={pushState} onSubscribe={subscribe} onUnsubscribe={unsubscribe} />
            <button className="push-btn" onClick={signOutUser}>Sign out</button>
          </div>
        </div>
      </header>

      {tab === "chat" ? <Chat /> : (
        <>
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
        </>
      )}

      {tab === "food" && entries.length > 0 && (
        <div className="day-total">
          <span>Total today</span>
          <span>{Math.round(totalKcal)} kcal</span>
        </div>
      )}
      {tab === "food" && <GarminConnect />}
      {tab === "food" && <Settings />}
    </div>
  );
}