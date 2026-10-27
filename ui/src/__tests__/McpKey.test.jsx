import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../firebase", () => ({
  auth: {},
  signInWithGoogle: vi.fn(),
  signInWithEmail: vi.fn(),
  registerWithEmail: vi.fn(),
  signOutUser: vi.fn(),
  getIdToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("../lib/api", () => ({
  createMcpKey: vi.fn(),
  createGarminUploadToken: vi.fn(),
}));

import { McpKey } from "../App.jsx";
import { createMcpKey } from "../lib/api";

const SECRET = "s3cr3t-key-value-123";

describe("McpKey", () => {
  beforeEach(() => {
    createMcpKey.mockReset().mockResolvedValue({ key: SECRET });
  });

  it("asks for confirmation before generating, and Cancel makes no request", async () => {
    const user = userEvent.setup();
    render(<McpKey />);
    await user.click(screen.getByRole("button", { name: "Generate MCP key" }));
    expect(screen.getByText(/replaces your current key/i)).toBeInTheDocument();
    expect(createMcpKey).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(createMcpKey).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Generate MCP key" })).toBeInTheDocument();
  });

  it("never renders the key as text, copies it, and clears on Done", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    const { container } = render(<McpKey />);
    await user.click(screen.getByRole("button", { name: "Generate MCP key" }));
    await user.click(screen.getByRole("button", { name: "Replace key" }));
    expect(createMcpKey).toHaveBeenCalledTimes(1);

    expect(await screen.findByRole("button", { name: "Copy key" })).toBeInTheDocument();
    expect(container.textContent).not.toContain(SECRET);

    await user.click(screen.getByRole("button", { name: "Copy key" }));
    expect(writeText).toHaveBeenCalledWith(SECRET);
    expect(screen.getByRole("button", { name: "Copied!" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Generate MCP key" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy|copied/i })).toBeNull();
  });

  it("shows an error and returns to idle when the request fails", async () => {
    createMcpKey.mockRejectedValue(new Error("500"));
    const user = userEvent.setup();
    render(<McpKey />);
    await user.click(screen.getByRole("button", { name: "Generate MCP key" }));
    await user.click(screen.getByRole("button", { name: "Replace key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not generate/i);
    expect(screen.getByRole("button", { name: "Generate MCP key" })).toBeInTheDocument();
  });

  describe("auto clear", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
    afterEach(() => vi.useRealTimers());

    it("clears the key after a minute", async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(<McpKey />);
      await user.click(screen.getByRole("button", { name: "Generate MCP key" }));
      await user.click(screen.getByRole("button", { name: "Replace key" }));
      expect(await screen.findByRole("button", { name: "Copy key" })).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(60001); });
      expect(screen.getByRole("button", { name: "Generate MCP key" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Copy key" })).toBeNull();
    });
  });
});
