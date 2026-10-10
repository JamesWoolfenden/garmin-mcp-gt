import React, { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { logEntry, deleteFood, deleteActivity, getBalance, sendChat, getChatHistory, createGarminUploadToken, getProfile, updateProfile, requestAccess, getCyclingForecast, getProgression } from "./lib/api";
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
  const hasMacros = entry.carbs_g || entry.protein_g || entry.fat_g;
  return (
    <div className="food-entry">
      <div className="food-entry-left">
        <span className="food-parsed">{entry.parsed}</span>
        <span className="food-time">
          {new Date(entry.logged_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
          {hasMacros && ` · ${entry.carbs_g}g C · ${entry.protein_g}g P · ${entry.fat_g}g F`}
        </span>
      </div>
      <div className="food-entry-right">
        <span className="food-kcal">{Math.round(entry.kcal)} kcal</span>
        <button className="delete-btn" onClick={() => onDelete(entry.id)} aria-label="Remove">×</button>
      </div>
    </div>
  );
}

function ActivityEntry({ activity, onDelete }) {
  return (
    <div className="food-entry">
      <div className="food-entry-left">
        <span className="food-parsed">{activity.name}</span>
        <span className="food-time">
          {new Date(activity.logged_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · manual
        </span>
      </div>
      <div className="food-entry-right">
        <span className="food-kcal">{activity.kcal} kcal</span>
        <button className="delete-btn" onClick={() => onDelete(activity.id)} aria-label="Remove">×</button>
      </div>
    </div>
  );
}

function ActivityForm({ onAdd }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setLoading(true);
    try {
      await onAdd(text.trim());
      setText(""); setOpen(false);
    } finally {
      setLoading(false);
    }
  };

  if (!open) return (
    <button className="activity-add-btn" onClick={() => setOpen(true)}>+ Add activity</button>
  );

  return (
    <form className="activity-form" onSubmit={submit}>
      <input className="log-input activity-name-input" value={text} onChange={e => setText(e.target.value)}
        placeholder="e.g. 10min indoor skydive" autoFocus autoComplete="off" />
      <button className="log-btn" type="submit" disabled={loading || !text.trim()}>
        {loading ? "…" : "Add"}
      </button>
      <button type="button" className="delete-btn" style={{fontSize:"14px"}} onClick={() => setOpen(false)}>×</button>
    </form>
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

function ReadinessBadge({ readiness }) {
  if (!readiness) return null;
  const dotClass = readiness.label.toLowerCase();
  return (
    <div className="readiness" title={readiness.driver}>
      <span className={`readiness-dot ${dotClass}`} />
      <span className="readiness-label">{readiness.label}</span>
      <span className="readiness-score">readiness · {readiness.score}/100</span>
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

  useEffect(() => {
    let cancelled = false;
    getChatHistory().then(history => {
      if (!cancelled && history.length > 0) setMessages(history);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", text }]);
    setLoading(true);
    try {
      const history = messages.slice(-10).map(m => ({ role: m.role, text: m.text }));
      const { response } = await sendChat(text, history);
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
          <div key={i} className={`chat-msg chat-msg-${m.role}`}>
            {m.role === "assistant" ? (
              <ReactMarkdown>{m.text}</ReactMarkdown>
            ) : (
              m.text
            )}
          </div>
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
  const [heightCm, setHeightCm] = useState("");
  const [waistCm, setWaistCm] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [locating, setLocating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(null);

  const applyProfile = (p) => {
    setKcalTarget(String(p.kcal_target || 2000));
    setNudgeTimes((p.nudge_times || []).join(", "));
    setHeightCm(p.height_cm ? String(p.height_cm) : "");
    setWaistCm(p.waist_cm ? String(p.waist_cm) : "");
    setLatitude(p.latitude != null ? String(p.latitude) : "");
    setLongitude(p.longitude != null ? String(p.longitude) : "");
    setSaved(p);
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLatitude(String(pos.coords.latitude.toFixed(4)));
        setLongitude(String(pos.coords.longitude.toFixed(4)));
        setLocating(false);
      },
      () => setLocating(false),
      { timeout: 10000 }
    );
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getProfile().then(p => { if (!cancelled) applyProfile(p); }).catch(() => {});
    return () => { cancelled = true; };
  }, [open]);

  useEffect(() => {
    let cancelled = false;
    getProfile().then(p => { if (!cancelled) setSaved(p); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const save = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const times = nudgeTimes.split(",").map(t => t.trim()).filter(Boolean);
      const updates = {
        kcal_target: parseInt(kcalTarget),
        nudge_times: times,
        ...(heightCm ? { height_cm: parseInt(heightCm) } : {}),
        ...(waistCm ? { waist_cm: parseInt(waistCm) } : {}),
        ...(latitude ? { latitude: parseFloat(latitude) } : {}),
        ...(longitude ? { longitude: parseFloat(longitude) } : {}),
      };
      const saved = await updateProfile(updates);
      applyProfile(saved);
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
              {saved.kcal_target} kcal
              {saved.height_cm ? ` · ${saved.height_cm}cm` : ""}
              {saved.waist_cm ? ` · waist ${saved.waist_cm}cm` : ""}
              {" · nudges "}{(saved.nudge_times || []).join(", ")}
            </p>
          )}
        </div>
        <button className="push-btn" onClick={() => setOpen(o => !o)}>
          {open ? "Cancel" : "Edit"}
        </button>
      </div>
      {open && (
        <>
        <form onSubmit={save} style={{display:"flex",flexDirection:"column",gap:"10px",marginTop:"12px"}}>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Daily kcal target
            <input className="log-input" type="number" value={kcalTarget}
              onChange={e => setKcalTarget(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}} min="500" max="6000" />
          </label>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Height (cm)
            <input className="log-input" type="number" value={heightCm}
              onChange={e => setHeightCm(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}} min="100" max="250"
              placeholder="e.g. 178" />
          </label>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Waist (cm)
            <input className="log-input" type="number" value={waistCm}
              onChange={e => setWaistCm(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}} min="50" max="200"
              placeholder="e.g. 82" />
          </label>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Nudge times (comma-separated)
            <input className="log-input" type="text" value={nudgeTimes}
              onChange={e => setNudgeTimes(e.target.value)}
              style={{display:"block",width:"100%",marginTop:"4px"}}
              placeholder="08:00, 13:00, 15:00, 20:00" />
          </label>
          <label style={{fontSize:"13px",color:"var(--text)"}}>
            Location (for the cycling forecast)
            <div style={{display:"flex",gap:"6px",marginTop:"4px"}}>
              <input className="log-input" type="number" step="any" value={latitude}
                onChange={e => setLatitude(e.target.value)}
                style={{flex:1}} placeholder="Latitude" />
              <input className="log-input" type="number" step="any" value={longitude}
                onChange={e => setLongitude(e.target.value)}
                style={{flex:1}} placeholder="Longitude" />
            </div>
            <button type="button" className="link-btn" style={{marginTop:"4px"}}
              onClick={useMyLocation} disabled={locating}>
              {locating ? "Locating…" : "Use my location"}
            </button>
          </label>
          <button className="log-btn" type="submit" disabled={loading}>
            {loading ? "Saving…" : "Save"}
          </button>
        </form>
        <GarminConnect nested />
        </>
      )}
    </div>
  );
}

function GarminConnect({ nested = false }) {
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
    <div style={nested ? {marginTop:"12px",paddingTop:"12px",borderTop:"1px solid var(--border)"} : {padding:"16px 20px",borderTop:"1px solid var(--border)"}}>
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

function AccessDenied() {
  const [status, setStatus] = useState("idle"); // idle | sending | sent | error

  const handleRequest = async () => {
    setStatus("sending");
    try {
      await requestAccess();
      setStatus("sent");
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className="signin">
      <h1 className="wordmark">fuel</h1>
      <div style={{textAlign:"center",maxWidth:"280px"}}>
        <p style={{fontSize:"18px",fontWeight:600,color:"var(--text)",marginBottom:"10px"}}>Access denied</p>
        <p style={{fontSize:"14px",color:"var(--muted)",lineHeight:1.6}}>
          This app is invite-only. Your account isn't on the access list.
        </p>
        {status === "sent" ? (
          <p style={{fontSize:"13px",color:"var(--muted)",marginTop:"16px"}}>
            Request sent — you'll get access once it's approved.
          </p>
        ) : (
          <>
            <button
              className="push-btn"
              style={{marginTop:"16px"}}
              disabled={status === "sending"}
              onClick={handleRequest}
            >
              {status === "sending" ? "Sending…" : "Request access"}
            </button>
            {status === "error" && (
              <p className="error-banner" style={{marginTop:"8px"}}>Couldn't send the request. Try again.</p>
            )}
          </>
        )}
      </div>
      <button className="push-btn" onClick={() => { signOutUser(); window.location.reload(); }}>
        Sign out
      </button>
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

function Sparkline({ data, width = 280, height = 48, color = "var(--accent)" }) {
  if (!data || data.length < 2) {
    return <p style={{fontSize:"12px",color:"var(--muted)"}}>Not enough data yet.</p>;
  }
  const ys = data.map(d => d.y);
  const min = Math.min(...ys), max = Math.max(...ys);
  const range = max - min || 1;
  const pad = 4;
  const points = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * (width - pad * 2);
    const y = height - pad - ((d.y - min) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{display:"block",maxWidth:"100%"}}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function DayCard({ day, best }) {
  return (
    <div style={{
      minWidth:"76px",padding:"10px 8px",borderRadius:"var(--radius)",textAlign:"center",flexShrink:0,
      background: best ? "var(--ok-dim)" : "var(--surface)",
      border: `1px solid ${best ? "var(--ok)" : "var(--border)"}`,
    }}>
      <p style={{fontSize:"11px",color:"var(--muted)"}}>{formatDate(day.date)}</p>
      <p style={{fontSize:"20px",margin:"4px 0"}}>{day.rideable ? "🚴" : "🌧"}</p>
      <p style={{fontSize:"11px",color:"var(--text)"}}>{Math.round(day.temp_max_c)}°</p>
      <p style={{fontSize:"10px",color:"var(--muted)"}}>{Math.round(day.max_wind_mph)}mph wind</p>
      {day.is_today && day.readiness && (
        <p style={{fontSize:"10px",color:"var(--accent)",marginTop:"2px"}}>{day.readiness.label}</p>
      )}
    </div>
  );
}

function CyclingProgress() {
  const [forecast, setForecast] = useState(null);
  const [forecastError, setForecastError] = useState(null);
  const [progression, setProgression] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getCyclingForecast().catch(e => ({ error: e.message })),
      getProgression().catch(() => ({ vo2max: [], weight_trend: [] })),
    ]).then(([f, p]) => {
      if (cancelled) return;
      if (f.error) setForecastError(f.error);
      else setForecast(f);
      setProgression(p);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <p className="empty">Loading…</p>;

  const vo2Points = (progression?.vo2max || [])
    .filter(d => d.vo2max != null)
    .map(d => ({ y: d.vo2max }));
  const weightPoints = (progression?.weight_trend || [])
    .filter(d => d.avg_weight_kg != null)
    .map(d => ({ y: d.avg_weight_kg }));
  const latestWeight = progression?.weight_trend?.length
    ? progression.weight_trend[progression.weight_trend.length - 1]
    : null;
  const latestVo2 = progression?.vo2max?.length
    ? [...progression.vo2max].reverse().find(d => d.vo2max != null)
    : null;

  return (
    <div style={{padding:"16px 20px",display:"flex",flexDirection:"column",gap:"24px"}}>
      <section>
        <h2 style={{fontSize:"14px",color:"var(--muted)",marginBottom:"10px"}}>Best days to ride this week</h2>
        {forecastError === "location_not_set" ? (
          <p style={{fontSize:"13px",color:"var(--muted)"}}>
            Set your location in Settings to see a cycling forecast.
          </p>
        ) : forecastError || !forecast ? (
          <p style={{fontSize:"13px",color:"var(--muted)"}}>Couldn't load the forecast.</p>
        ) : (
          <div style={{display:"flex",gap:"8px",overflowX:"auto",paddingBottom:"4px"}}>
            {forecast.days.map(d => (
              <DayCard key={d.date} day={d} best={forecast.best_dates.includes(d.date)} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 style={{fontSize:"14px",color:"var(--muted)",marginBottom:"10px"}}>Fitness (VO2max)</h2>
        <Sparkline data={vo2Points} />
        <p style={{fontSize:"12px",color:"var(--muted)",marginTop:"4px"}}>
          {latestVo2 ? `Latest: ${latestVo2.vo2max}` : "No VO2max data yet."}
        </p>
      </section>

      <section>
        <h2 style={{fontSize:"14px",color:"var(--muted)",marginBottom:"10px"}}>Weight trend</h2>
        <Sparkline data={weightPoints} color="var(--ok)" />
        <p style={{fontSize:"12px",color:"var(--muted)",marginTop:"4px"}}>
          {latestWeight
            ? `${latestWeight.avg_weight_kg}kg${
                latestWeight.change_from_prev_week_kg != null
                  ? ` · ${latestWeight.change_from_prev_week_kg > 0 ? "+" : ""}${latestWeight.change_from_prev_week_kg}kg vs last week`
                  : ""
              }`
            : "No weight data yet."}
        </p>
      </section>
    </div>
  );
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function formatDate(iso) {
  if (iso === todayISO()) return "Today";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export default function App() {
  const user = useAuth();
  const [accessDenied, setAccessDenied] = useState(false);
  const [tab, setTab] = useState("food"); // food | chat
  const [viewDate, setViewDate] = useState(todayISO());
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState([]);
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const { state: pushState, subscribe, unsubscribe } = usePush();
  const isToday = viewDate === todayISO();

  const loadData = useCallback(async (date) => {
    try {
      const bal = await getBalance(date === todayISO() ? undefined : date);
      setEntries(bal.entries || []);
      setBalance(bal);
    } catch (e) {
      if (e.message === "ACCESS_DENIED") {
        setAccessDenied(true);
      } else {
        setError("Could not load data");
      }
    }
  }, []);

  useEffect(() => { if (user) loadData(viewDate); }, [loadData, user, viewDate]);

  const shiftDate = (delta) => {
    const d = new Date(viewDate + "T12:00:00");
    d.setDate(d.getDate() + delta);
    const next = d.toISOString().slice(0, 10);
    if (next <= todayISO()) setViewDate(next);
  };

  const handleLog = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const newEntry = await logEntry(input.trim());
      setInput("");
      if (newEntry.type === "food") {
        setEntries(prev => [newEntry, ...prev]);
      }
      // Refresh balance in background — don't block on Garmin + Claude
      loadData(viewDate);
    } catch (e) {
      setError("Failed to log — try again");
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleDelete = async (id) => {
    setEntries(prev => prev.filter(e => e.id !== id));
    try {
      await deleteFood(id);
      loadData(viewDate);
    } catch (e) {
      setError("Could not remove entry");
    }
  };

  const totalKcal = entries.reduce((s, e) => s + e.kcal, 0);
  const manualActivities = balance?.manual_activities || [];

  const handleDeleteActivity = async (id) => {
    await deleteActivity(id);
    loadData(viewDate);
  };

  if (user === undefined) return <div className="app"><p style={{padding:"2rem"}}>Loading…</p></div>;
  if (accessDenied) return <AccessDenied />;
  if (user === null) return <SignIn />;

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <span className="wordmark">fuel</span>
          <div style={{display:"flex",gap:"0.5rem",alignItems:"center"}}>
            <button className={`push-btn${tab === "food" ? " active" : ""}`} onClick={() => setTab("food")}>Log</button>
            <button className={`push-btn${tab === "ride" ? " active" : ""}`} onClick={() => setTab("ride")}>Ride</button>
            <button className={`push-btn${tab === "chat" ? " active" : ""}`} onClick={() => setTab("chat")}>Ask</button>
            <PushToggle pushState={pushState} onSubscribe={subscribe} onUnsubscribe={unsubscribe} />
            <button className="push-btn" onClick={signOutUser}>Sign out</button>
          </div>
        </div>
      </header>

      {tab === "chat" ? <Chat /> : tab === "ride" ? <CyclingProgress /> : (
        <>
          <div className="date-nav">
            <button className="date-nav-btn" onClick={() => shiftDate(-1)}>‹</button>
            <span className="date-nav-label">{formatDate(viewDate)}</span>
            <button className="date-nav-btn" onClick={() => shiftDate(1)} disabled={isToday}>›</button>
          </div>

          {balance && (
            <div className="balance-section">
              {balance.status !== "historical" && (
                <BalanceBar kcalIn={balance.kcal_in} kcalBurned={balance.kcal_burned} kcalTarget={balance.kcal_target} />
              )}
              <Recommendation text={balance.recommendation} status={balance.status} />
              <ReadinessBadge readiness={balance.readiness} />
              {balance.garmin_available === false && balance.status !== "historical" && (
                <p style={{fontSize:"12px",color:"var(--muted)",textAlign:"center",margin:"4px 0 0"}}>
                  ⚠ Garmin disconnected — open Settings to reconnect
                </p>
              )}
            </div>
          )}

          {isToday && (
            <form className="log-form" onSubmit={handleLog}>
              <input
                ref={inputRef}
                className="log-input"
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder="granola and coffee… or 45min ride…"
                disabled={loading}
                autoComplete="off"
                autoCapitalize="none"
              />
              <button className="log-btn" type="submit" disabled={loading || !input.trim()}>
                {loading ? "…" : "Log"}
              </button>
            </form>
          )}

          {error && <div className="error-banner">{error}</div>}

          <div className="entries">
            {manualActivities.length > 0 && manualActivities.map(a => (
              <ActivityEntry key={a.id} activity={a} onDelete={handleDeleteActivity} />
            ))}
            {manualActivities.length > 0 && <div className="entries-divider" />}
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
          <span>
            {balance?.macros_today && (
              <span className="day-macros">
                {balance.macros_today.carbs_g}g C · {balance.macros_today.protein_g}g P · {balance.macros_today.fat_g}g F ·{" "}
              </span>
            )}
            {Math.round(totalKcal)} kcal
          </span>
        </div>
      )}
      {tab === "food" && <Settings />}
    </div>
  );
}