import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const mockApi = vi.hoisted(() => ({ getChatHistory: vi.fn() }));

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
  getProfile: vi.fn().mockResolvedValue({ kcal_target: 2000, nudge_times: ["08:00"] }),
  updateProfile: vi.fn().mockResolvedValue({}),
  sendChat: vi.fn(),
  getChatHistory: mockApi.getChatHistory,
  createGarminUploadToken: vi.fn().mockResolvedValue({ token: "test-token" }),
  subscribePush: vi.fn(),
  unsubscribePush: vi.fn(),
}));

Object.defineProperty(navigator, "serviceWorker", {
  value: {
    register: vi.fn().mockResolvedValue({
      pushManager: { getSubscription: vi.fn().mockResolvedValue(null) },
    }),
    ready: Promise.resolve({ pushManager: { subscribe: vi.fn() } }),
  },
  writable: true,
});
Object.defineProperty(window, "PushManager", { value: {}, writable: true });
Object.defineProperty(window, "Notification", {
  value: { requestPermission: vi.fn().mockResolvedValue("granted") },
  writable: true,
});

describe("Chat markdown rendering", () => {
  it("renders assistant markdown as real elements, not literal syntax", async () => {
    mockApi.getChatHistory.mockResolvedValue([
      {
        role: "assistant",
        text: "Your HRV is **62ms**, which is above baseline.\n\n- Sleep: 85/100\n- Steps: 8,200",
      },
    ]);
    render(<App />);
    await userEvent.click(await screen.findByText("Ask"));

    expect(await screen.findByText("62ms", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Sleep: 85/100")).toBeInTheDocument();
    // The literal markdown syntax should not appear anywhere in the chat.
    expect(screen.queryByText(/\*\*62ms\*\*/)).not.toBeInTheDocument();
  });

  it("renders user messages as plain text, not parsed markdown", async () => {
    mockApi.getChatHistory.mockResolvedValue([
      { role: "user", text: "what about **today**?" },
    ]);
    render(<App />);
    await userEvent.click(await screen.findByText("Ask"));

    expect(await screen.findByText("what about **today**?")).toBeInTheDocument();
    expect(screen.queryByText("today", { selector: "strong" })).not.toBeInTheDocument();
  });
});
