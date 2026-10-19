import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fixtureApi } from "../src/api";
import { App } from "../src/App";
import { StoreProvider } from "../src/store";

const visit = async (path: string) => {
  await act(async () => {
    window.location.hash = path;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
};

const mount = () =>
  render(
    <StoreProvider api={fixtureApi(0)}>
      <App />
    </StoreProvider>,
  );

const runSample = async (label: string) => {
  await visit("/get-cash");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: new RegExp(label) })));
  await waitFor(() => expect(window.location.hash).toMatch(/^#\/invoice\//));
};

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = "";
});
afterEach(cleanup);

describe("the SME owner's app (sample mode)", () => {
  it("starts empty and invites the first invoice", () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Home" })).toBeTruthy();
    expect(screen.getByText("Turn an unpaid invoice into cash today")).toBeTruthy();
    expect(screen.getByText(/Sample mode/)).toBeTruthy();
  });

  it("funds the clean invoice and shows the money", async () => {
    mount();
    await runSample("A clean invoice");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("You got THB 524,300.00");
    expect(screen.getByText("Most cash today within your cost cap")).toBeTruthy();
    await visit("/");
    expect(screen.getAllByText("Funded · waiting for buyer").length).toBeGreaterThan(0);
  });

  it("settles the invoice when the buyer pays", async () => {
    mount();
    await runSample("A clean invoice");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /pays today/ })));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/^Paid in full: you received THB 743,809.43/),
    );
  });

  it("refuses the same invoice twice", async () => {
    mount();
    await runSample("A clean invoice");
    await runSample("A clean invoice");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("We could not finance this invoice");
    expect(screen.getAllByText(/already financed, so it cannot be financed twice/).length).toBeGreaterThan(0);
  });

  it("holds hidden instructions for the owner and counts it on Needs you", async () => {
    mount();
    await runSample("hidden instructions");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("We held this invoice");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByLabelText("1 waiting")).toBeTruthy();
    await visit("/needs-you");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Close it" })));
    expect(screen.getByText("Nothing needs you")).toBeTruthy();
  });

  it("runs the six protection tests and reports every one blocked", async () => {
    mount();
    await visit("/activity");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Run the six tests" })));
    expect(await screen.findAllByText(/^Blocked: /)).toHaveLength(6);
    expect(screen.getByText("Attempts blocked").nextSibling?.textContent).toBe("6");
  });

  it("rewrites the rule sentence from the sliders and saves it for the tab", async () => {
    mount();
    await visit("/rule");
    fireEvent.change(screen.getByLabelText("Most I will take up front"), { target: { value: "60" } });
    expect(screen.getByText(/never advance more than 60%/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save and sign" })));
    expect(await screen.findByText(/Saved for this tab/)).toBeTruthy();
    await visit("/");
    expect(screen.getByText(/never advance more than 60%/)).toBeTruthy();
  });
});
