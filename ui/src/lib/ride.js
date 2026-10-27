// Ride-planning helpers for the Ride tab (pure, so they're easy to test).

export const RIDE_TYPES = [
  { id: "road", label: "Road" },
  { id: "gravel", label: "Gravel" },
  { id: "mtb", label: "MTB" },
];
export const RIDE_LENGTHS = [1, 2, 3, 4];

const KEY = "fuel.ridePrefs";
const DEFAULTS = { rideType: "road", minHours: 2 };

// "14:00–17:00"
export const formatWindow = (w) => `${w.start}–${w.end}`;

export const RATING_COLOR = {
  good: "var(--ok)",
  ok: "var(--warn)",
  poor: "var(--over)",
};

// Does hour "HH:MM" fall inside window w? (window end is exclusive)
export function inWindow(time, w) {
  return !!w && time >= w.start && time < w.end;
}

export function loadRidePrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || "{}");
    return {
      rideType: RIDE_TYPES.some((t) => t.id === p.rideType) ? p.rideType : DEFAULTS.rideType,
      minHours: RIDE_LENGTHS.includes(p.minHours) ? p.minHours : DEFAULTS.minHours,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveRidePrefs(prefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* private mode / storage blocked: the choice just won't persist */
  }
}
