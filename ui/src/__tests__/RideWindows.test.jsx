import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../firebase", () => ({
  auth: {},
  signInWithGoogle: vi.fn(),
  signInWithEmail: vi.fn(),
  registerWithEmail: vi.fn(),
  signOutUser: vi.fn(),
  getIdToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("../lib/api", () => ({
  getCyclingForecast: vi.fn(),
  getProgression: vi.fn(),
  createGarminUploadToken: vi.fn(),
  createMcpKey: vi.fn(),
}));

import { CyclingProgress, RidePrefs, BestTimes } from "../App.jsx";
import { getCyclingForecast, getProgression } from "../lib/api";
import { formatWindow, inWindow, loadRidePrefs, saveRidePrefs } from "../lib/ride";

const WINDOW = {
  start: "14:00", end: "17:00", hours: 3, good_hours: 3, score: 3,
  avg_temp_c: 12.4, max_wind_mph: 9.6, max_precip_chance_pct: 5, total_precip_mm: 0,
};

const forecast = (over = {}) => ({
  ride_type: "road",
  min_hours: 2,
  best_dates: ["2026-10-29"],
  best_windows: [{ date: "2026-10-29", ...WINDOW }],
  days: [
    {
      date: "2026-10-29", condition: "Cloudy", temp_min_c: 8, temp_max_c: 13,
      max_wind_mph: 12, wind_direction: "SW", rideable: true,
      ride_windows: [WINDOW], best_window: WINDOW,
      hourly: Array.from({ length: 24 }, (_, h) => ({
        time: `${String(h).padStart(2, "0")}:00`, condition: "Cloudy", temp_c: 11,
        precipitation_chance_pct: 5, precipitation_mm: 0, wind_mph: 8,
        ride_rating: h >= 14 && h < 17 ? "good" : "poor", surface_wet: false,
      })),
    },
    {
      date: "2026-10-30", condition: "Rain", temp_min_c: 9, temp_max_c: 11,
      max_wind_mph: 22, wind_direction: "W", rideable: false,
      ride_windows: [], best_window: null,
      hourly: Array.from({ length: 24 }, (_, h) => ({
        time: `${String(h).padStart(2, "0")}:00`, condition: "Rain", temp_c: 10,
        precipitation_chance_pct: 90, precipitation_mm: h === 12 ? 0 : 1.2, wind_mph: 20,
        ride_rating: "poor", surface_wet: true,
      })),
    },
  ],
  ...over,
});

describe("ride helpers", () => {
  beforeEach(() => localStorage.clear());

  it("formats a window and tests hour membership (end exclusive)", () => {
    expect(formatWindow(WINDOW)).toBe("14:00–17:00");
    expect(inWindow("14:00", WINDOW)).toBe(true);
    expect(inWindow("16:00", WINDOW)).toBe(true);
    expect(inWindow("17:00", WINDOW)).toBe(false);
    expect(inWindow("13:00", WINDOW)).toBe(false);
    expect(inWindow("14:00", null)).toBe(false);
  });

  it("defaults to road / 2h and ignores corrupt stored prefs", () => {
    expect(loadRidePrefs()).toEqual({ rideType: "road", minHours: 2 });
    localStorage.setItem("fuel.ridePrefs", "{not json");
    expect(loadRidePrefs()).toEqual({ rideType: "road", minHours: 2 });
    localStorage.setItem("fuel.ridePrefs", JSON.stringify({ rideType: "tank", minHours: 99 }));
    expect(loadRidePrefs()).toEqual({ rideType: "road", minHours: 2 });
  });

  it("round-trips saved prefs", () => {
    saveRidePrefs({ rideType: "mtb", minHours: 3 });
    expect(loadRidePrefs()).toEqual({ rideType: "mtb", minHours: 3 });
  });
});

describe("RidePrefs / BestTimes", () => {
  it("reports the new choice and keeps the other one", async () => {
    const onChange = vi.fn();
    render(<RidePrefs rideType="road" minHours={2} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Road" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "MTB" }));
    expect(onChange).toHaveBeenLastCalledWith({ rideType: "mtb", minHours: 2 });
    await userEvent.click(screen.getByRole("button", { name: "3h" }));
    expect(onChange).toHaveBeenLastCalledWith({ rideType: "road", minHours: 3 });
  });

  it("lists windows with conditions and picks a day on click", async () => {
    const onPick = vi.fn();
    render(<BestTimes windows={[{ date: "2026-10-29", ...WINDOW }]} onPick={onPick} />);
    expect(screen.getByText("14:00–17:00")).toBeInTheDocument();
    expect(screen.getByText(/12° · 10mph · dry/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("14:00–17:00"));
    expect(onPick).toHaveBeenCalledWith("2026-10-29");
  });

  it("renders nothing without windows", () => {
    const { container } = render(<BestTimes windows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Ride tab", () => {
  beforeEach(() => {
    localStorage.clear();
    getCyclingForecast.mockReset().mockResolvedValue(forecast());
    getProgression.mockReset().mockResolvedValue({ vo2max: [], weight_trend: [] });
  });

  it("shows the best window on each day card and says when there is none", async () => {
    render(<CyclingProgress />);
    expect((await screen.findAllByText("14:00–17:00")).length).toBeGreaterThan(0);
    expect(screen.getByText("no window")).toBeInTheDocument();
    expect(getCyclingForecast).toHaveBeenCalledWith("road", 2);
  });

  it("refetches for the chosen ride type and remembers it", async () => {
    render(<CyclingProgress />);
    await screen.findAllByText("14:00–17:00");
    await userEvent.click(screen.getByRole("button", { name: "MTB" }));
    await waitFor(() => expect(getCyclingForecast).toHaveBeenLastCalledWith("mtb", 2));
    await userEvent.click(screen.getByRole("button", { name: "4h" }));
    await waitFor(() => expect(getCyclingForecast).toHaveBeenLastCalledWith("mtb", 4));
    expect(loadRidePrefs()).toEqual({ rideType: "mtb", minHours: 4 });
  });

  it("starts from the saved choice", async () => {
    saveRidePrefs({ rideType: "gravel", minHours: 3 });
    render(<CyclingProgress />);
    await screen.findAllByText("14:00–17:00");
    expect(getCyclingForecast).toHaveBeenCalledWith("gravel", 3);
  });

  it("explains an empty week instead of showing nothing", async () => {
    getCyclingForecast.mockResolvedValue(forecast({ best_windows: [], best_dates: [] }));
    render(<CyclingProgress />);
    expect(await screen.findByText(/No 2h\+ window this week for a road ride/)).toBeInTheDocument();
  });

  it("opens an hourly breakdown that marks the ride window and damp roads", async () => {
    render(<CyclingProgress />);
    await screen.findAllByText("14:00–17:00");
    await userEvent.click(screen.getByText("no window").closest("div"));
    // 12:00 is dry but the road is still wet from the rain either side of it
    expect(await screen.findByText(/Rain · damp roads/)).toBeInTheDocument();
    expect(screen.getByText("No good window to ride today.")).toBeInTheDocument();
    expect(screen.getAllByText("1.2mm").length).toBeGreaterThan(0);
  });
});

describe("CollapsibleSection", () => {
  it("toggles and remembers closed state", async () => {
    localStorage.clear();
    const { CollapsibleSection } = await import("../App");
    const { unmount } = render(<CollapsibleSection id="t" title="T"><p>body</p></CollapsibleSection>);
    expect(screen.getByText("body")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /T/ }));
    expect(screen.queryByText("body")).toBeNull();
    unmount();
    render(<CollapsibleSection id="t" title="T"><p>body</p></CollapsibleSection>);
    expect(screen.queryByText("body")).toBeNull();
  });
});
