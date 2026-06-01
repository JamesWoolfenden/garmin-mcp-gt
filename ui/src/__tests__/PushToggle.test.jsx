import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import App from "../App.jsx";

// Mock the API module so no network calls are made
vi.mock("../lib/api", () => ({
  logFood: vi.fn(),
  getTodayFood: vi.fn().mockResolvedValue({ entries: [], total_kcal: 0 }),
  deleteFood: vi.fn(),
  getBalance: vi.fn().mockResolvedValue({
    kcal_in: 0,
    kcal_burned: 0,
    kcal_target: 2000,
    status: "on_track",
    recommendation: "Looking good.",
  }),
  subscribePush: vi.fn(),
  unsubscribePush: vi.fn(),
}));

// Mock service worker APIs
Object.defineProperty(navigator, "serviceWorker", {
  value: {
    register: vi.fn().mockResolvedValue({
      pushManager: { getSubscription: vi.fn().mockResolvedValue(null) },
    }),
    ready: Promise.resolve({
      pushManager: {
        subscribe: vi.fn().mockResolvedValue({
          toJSON: () => ({ endpoint: "https://example.com", keys: {} }),
        }),
      },
    }),
  },
  writable: true,
});

Object.defineProperty(window, "PushManager", { value: {}, writable: true });
Object.defineProperty(window, "Notification", {
  value: { requestPermission: vi.fn().mockResolvedValue("granted") },
  writable: true,
});

describe("App", () => {
  it("renders without crashing", async () => {
    render(<App />);
    expect(screen.getByText("fuel")).toBeInTheDocument();
  });

  it("shows Enable nudges button when not subscribed", async () => {
    render(<App />);
    expect(await screen.findByText("Enable nudges")).toBeInTheDocument();
  });
});

describe("PushToggle states", () => {
  it("shows blocked message when notifications denied", async () => {
    window.Notification.requestPermission = vi.fn().mockResolvedValue("denied");
    render(<App />);
    const btn = await screen.findByText("Enable nudges");
    await userEvent.click(btn);
    expect(await screen.findByText(/Notifications blocked/i)).toBeInTheDocument();
  });
});
