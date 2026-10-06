import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("../firebase", () => ({
  auth: {},
  signInWithGoogle: vi.fn(),
  signInWithEmail: vi.fn(),
  registerWithEmail: vi.fn(),
  signOutUser: vi.fn(),
  getIdToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn().mockReturnValue({ uid: "test-user", email: "test@example.com" }),
}));

import App from "../App.jsx";

const mockApi = vi.hoisted(() => ({ getBalance: vi.fn() }));

vi.mock("../lib/api", () => ({
  logFood: vi.fn(),
  getTodayFood: vi.fn().mockResolvedValue({ entries: [], total_kcal: 0 }),
  deleteFood: vi.fn(),
  getBalance: mockApi.getBalance,
  getProfile: vi.fn().mockResolvedValue({ kcal_target: 2000, nudge_times: ["08:00", "13:00"] }),
  updateProfile: vi.fn().mockResolvedValue({}),
  sendChat: vi.fn(),
  createGarminUploadToken: vi.fn().mockResolvedValue({ token: "test-token" }),
  subscribePush: vi.fn(),
  unsubscribePush: vi.fn(),
}));

Object.defineProperty(navigator, "serviceWorker", {
  value: {
    register: vi.fn().mockResolvedValue({
      pushManager: { getSubscription: vi.fn().mockResolvedValue(null) },
    }),
    ready: Promise.resolve({
      pushManager: { subscribe: vi.fn() },
    }),
  },
  writable: true,
});

Object.defineProperty(window, "PushManager", { value: {}, writable: true });
Object.defineProperty(window, "Notification", {
  value: { requestPermission: vi.fn().mockResolvedValue("granted") },
  writable: true,
});

describe("ReadinessBadge", () => {
  it("shows the label and score when readiness data is present", async () => {
    mockApi.getBalance.mockResolvedValue({
      kcal_in: 0,
      kcal_burned: 0,
      kcal_target: 2000,
      status: "on_track",
      recommendation: "Looking good.",
      readiness: { score: 82, label: "Fresh", driver: "Lowest signal: HRV (80)" },
    });
    render(<App />);
    expect(await screen.findByText("Fresh")).toBeInTheDocument();
    expect(await screen.findByText(/readiness · 82\/100/)).toBeInTheDocument();
  });

  it("renders nothing when readiness is null", async () => {
    mockApi.getBalance.mockResolvedValue({
      kcal_in: 0,
      kcal_burned: 0,
      kcal_target: 2000,
      status: "on_track",
      recommendation: "Looking good.",
      readiness: null,
    });
    render(<App />);
    await screen.findByText("Looking good.");
    expect(screen.queryByText(/readiness ·/)).not.toBeInTheDocument();
  });
});
