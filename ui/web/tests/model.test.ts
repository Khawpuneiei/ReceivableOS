import { describe, expect, it } from "vitest";
import { SAMPLES, SAVED_MANDATE, savedAttack } from "../src/api";
import { activity, activityCsv, advance, type Case, onPayment, ruleChecks, status, totals } from "../src/model";
import { money } from "../src/money";

const run = (id: string) => SAMPLES.find((s) => s.id === id)!.run;
const caseOf = (id: string, extra: Partial<Case> = {}): Case => ({ id, at: "2026-10-19T02:00:00.000Z", filename: `${id}.pdf`, flow: run(id), ...extra });

describe("status", () => {
  it("funds the clean invoice", () => {
    const c = caseOf("happy");
    expect(status(c).key).toBe("funded");
    expect(money(advance(c.flow)!)).toBe("THB 524,300.00");
    expect(money(onPayment(c.flow)!)).toBe("THB 219,509.43");
  });

  it("holds an invoice with hidden instructions for a person", () => {
    const s = status(caseOf("injected"));
    expect(s.key).toBe("held");
    expect(s.why).toContain("The file contains text that tries to give our AI instructions");
  });

  it("declines altered totals and a re-saved duplicate", () => {
    expect(status(caseOf("inflated")).key).toBe("declined");
    const dup = status(caseOf("duplicate"));
    expect(dup.label).toBe("Declined · already financed");
    expect(dup.why[0]).toMatch(/already financed/);
  });

  it("marks a settled invoice paid and counts both payments as received", () => {
    const paid = caseOf("happy", { settlement: { status: "executed", chain_ref: "mock:0x12" } });
    expect(status(paid).key).toBe("paid");
    expect(money(totals([paid], []).received)).toBe("THB 743,809.43");
  });
});

describe("rule checks", () => {
  it("compares the draw, not the invoice, with the ask-me limit", () => {
    const checks = ruleChecks(run("happy"), SAVED_MANDATE);
    expect(checks.map(([t]) => t)).toContain("No approval needed");
    const strict = { ...SAVED_MANDATE, human_review_above: "500000.00" };
    expect(ruleChecks(run("happy"), strict).map(([t]) => t)).toContain("Above your ask-me limit");
  });
});

describe("activity", () => {
  it("lists money, holds and blocked attempts newest first", () => {
    const later = { id: "p1", at: "2026-10-19T03:00:00.000Z", attack: savedAttack("A1"), saved: true };
    const events = activity([caseOf("happy"), caseOf("injected")], [later]);
    expect(events[0].title).toBe("Blocked: a payment to an account that is not yours");
    expect(events.map((e) => e.title)).toContain("Advance received");
    expect(events.map((e) => e.title)).toContain("Held: SFP-INV-2026-0143");
    expect(totals([caseOf("happy"), caseOf("duplicate")], [later]).blocked).toBe(2);
  });

  it("never reports an attack that got through as blocked", () => {
    const through = { ...savedAttack("A3"), status: "executed" };
    const [e] = activity([], [{ id: "p", at: "2026-10-19T03:00:00.000Z", attack: through, saved: false }]);
    expect(e.title).toMatch(/^Not stopped/);
    expect(totals([], [{ id: "p", at: "x", attack: through, saved: false }]).blocked).toBe(0);
  });

  it("writes a CSV a spreadsheet cannot run as formulas", () => {
    const csv = activityCsv([{ id: "1", at: "t", tone: "bad", title: "=HYPERLINK(1)", detail: 'say "hi"', money: false }]);
    expect(csv).toContain(`"'=HYPERLINK(1)"`);
    expect(csv).toContain('"say ""hi"""');
  });
});
