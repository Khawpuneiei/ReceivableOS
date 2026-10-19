import { describe, expect, it } from "vitest";
import { day, lesser, minus, money, percent, plus, scorePercent, times, toMicros } from "../src/money";

describe("money", () => {
  it("formats decimal strings without floats", () => {
    expect(money("749000.00")).toBe("THB 749,000.00");
    expect(money("0.005")).toBe("THB 0.01");
    expect(money(minus("749000.00", "524300.00", "5347.86"))).toBe("THB 219,352.14");
    expect(money(plus("0.10", "0.20"))).toBe("THB 0.30");
  });

  it("multiplies an amount by a rate exactly", () => {
    expect(money(times("749000.00", "0.70"))).toBe("THB 524,300.00");
    expect(money(lesser("524300.00", times("749000.00", "0.80")))).toBe("THB 524,300.00");
  });

  it("shows rates and scores as percentages", () => {
    expect(percent("0.70")).toBe("70%");
    expect(percent("0.1095")).toBe("10.95%");
    expect(percent("0.009")).toBe("0.9%");
    expect(scorePercent(0.002702)).toBe("0.27%");
  });

  it("refuses anything that is not a decimal string", () => {
    expect(() => toMicros("1e5")).toThrow();
    expect(() => toMicros("THB 5")).toThrow();
  });

  it("reads ISO dates as calendar days", () => {
    expect(day("2026-11-15")).toBe("15 Nov 2026");
  });
});
