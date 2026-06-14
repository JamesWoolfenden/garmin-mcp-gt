const CACHE_VERSION = "fuel-v2";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;
const ALL_CACHES = [STATIC_CACHE, API_CACHE];

const API_HOST = "fuel-backend-430943803039.europe-west1.run.app";

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(["/", "/index.html"])).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !ALL_CACHES.includes(k)).map((k) => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Don't cache Firebase, Google, or other third-party requests
  if (url.origin !== self.location.origin && url.hostname !== API_HOST) return;

  if (url.hostname === API_HOST) {
    // API: network-first, fall back to cache
    e.respondWith(
      fetch(request)
        .then((res) => {
          const clone = res.clone();
          caches.open(API_CACHE).then((c) => c.put(request, clone));
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Static assets with content hash in URL: cache-first
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((res) => {
          caches.open(STATIC_CACHE).then((c) => c.put(request, res.clone()));
          return res;
        });
      })
    );
    return;
  }

  // App shell: network-first, fall back to cached index.html
  e.respondWith(
    fetch(request)
      .then((res) => {
        caches.open(STATIC_CACHE).then((c) => c.put(request, res.clone()));
        return res;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match("/index.html")))
  );
});

self.addEventListener("push", (e) => {
  let title = "Fuel";
  let body = "Check your nutrition and activity balance.";
  let url = "/";

  if (e.data) {
    try {
      const data = e.data.json();
      title = data.title || title;
      body = data.body || body;
      url = data.url || url;
    } catch {
      body = e.data.text() || body;
    }
  }

  e.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: "fuel-nudge",
      data: { url },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
      const existing = cs.find((c) => c.url.includes(self.location.origin));
      if (existing) return existing.focus();
      return clients.openWindow(e.notification.data?.url || "/");
    })
  );
});
