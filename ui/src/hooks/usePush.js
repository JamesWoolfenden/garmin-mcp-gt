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