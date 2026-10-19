import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fixtureApi, liveApi, plainError, sampleFor } from "../src/api";

afterEach(() => vi.unstubAllGlobals());

describe("fixture mode", () => {
  it("picks the saved run by demo file name", () => {
    expect(sampleFor("02_injected.pdf").id).toBe("injected");
    expect(sampleFor("my-invoice.pdf").id).toBe("happy");
  });

  it("refuses the clean invoice the second time, like the registry does", async () => {
    const api = fixtureApi(0);
    expect((await api.runFlow(new Blob([]), "01_happy.pdf", "mdt_001")).wallet?.status).toBe("executed");
    const again = await api.runFlow(new Blob([]), "01_happy.pdf", "mdt_001");
    expect(again.register?.block_reason).toBe("DuplicateReceivable");
  });
});

describe("live mode", () => {
  const answer = (status: number, body: unknown) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

  it("posts the file and mandate to /api/flow/run", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ outcome: "executed" }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await liveApi().runFlow(new Blob(["x"]), "a.pdf", "mdt_001");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/flow/run");
    expect((init.body as FormData).get("mandate_id")).toBe("mdt_001");
  });

  it("says plainly which service failed", async () => {
    answer(502, { detail: 'http://ocr:8001/ocr/extract answered 415: {"detail": "not a PDF"}' });
    await expect(liveApi().runFlow(new Blob([]), "a.txt", "mdt_001")).rejects.toThrow("the invoice reader refused the request: not a PDF");
  });

  it("treats a missing route as unsupported, and no answer as unavailable", async () => {
    answer(404, { detail: "Not Found" });
    await expect(liveApi().confirm("tx_1")).rejects.toMatchObject({ kind: "unsupported" });
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(liveApi().attack("A1")).rejects.toBeInstanceOf(ApiError);
  });

  it("never sends the orchestrator token from the browser: the server adds it", () => {
    const sources = import.meta.glob<string>("../src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true });
    expect(Object.keys(sources).length).toBeGreaterThan(10);
    for (const text of Object.values(sources)) expect(text).not.toMatch(/X-Orchestrator-Token|import\.meta\.env\.\w*TOKEN/i);
  });
});

describe("plainError", () => {
  it("falls back to the raw detail", () => {
    expect(plainError("boom")).toBe("a service failed: boom");
  });
});
