// App state: the owner's invoices, the protection checks they ran, and their rule. Kept for the browser tab
// (sessionStorage) so a refresh does not lose a demo; the services stay the source of truth.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { type Api, ApiError, ATTACK_CASES, defaultApi, SAVED_MANDATE, SAVED_RULE_TEXT, savedAttack } from "./api";
import type { Case, Protection } from "./model";
import type { Mandate } from "./types";

export interface State {
  cases: Case[];
  protections: Protection[];
  mandate: Mandate;
  ruleText: string;
}

const KEY = "receivableos.web.v1";
const EMPTY: State = { cases: [], protections: [], mandate: SAVED_MANDATE, ruleText: SAVED_RULE_TEXT };

function load(): State {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<State>) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function save(state: State): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // private window or storage full: the app still works for this page view
  }
}

let seq = 0;
const newId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(seq++).toString(36)}`;

export interface Store {
  state: State;
  api: Api;
  run(file: Blob, filename: string): Promise<Case>;
  repay(caseId: string): Promise<void>;
  confirm(caseId: string): Promise<string | null>;
  setOwner(caseId: string, owner: Case["owner"]): void;
  testProtections(): Promise<void>;
  saveRule(mandate: Mandate, text: string): Promise<string>;
  reset(): void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ api = defaultApi(), children }: { api?: Api; children: ReactNode }) {
  const [state, setState] = useState<State>(load);
  useEffect(() => save(state), [state]);

  const patchCase = useCallback(
    (id: string, patch: Partial<Case>) =>
      setState((s) => ({ ...s, cases: s.cases.map((c) => (c.id === id ? { ...c, ...patch } : c)) })),
    [],
  );

  const store = useMemo<Store>(
    () => ({
      state,
      api,
      async run(file, filename) {
        const flow = await api.runFlow(file, filename, state.mandate.mandate_id);
        const c: Case = { id: newId("case"), at: new Date().toISOString(), filename, flow };
        setState((s) => ({ ...s, cases: [c, ...s.cases] }));
        return c;
      },
      async repay(caseId) {
        const c = state.cases.find((x) => x.id === caseId);
        if (!c) return;
        const settlement = await api.repay(c.flow.ocr.invoice_id);
        patchCase(caseId, { settlement });
      },
      async confirm(caseId) {
        const c = state.cases.find((x) => x.id === caseId);
        if (!c?.flow.wallet) return null;
        try {
          const wallet = await api.confirm(c.flow.wallet.tx_id);
          patchCase(caseId, { owner: "approved", flow: { ...c.flow, wallet } });
          return null;
        } catch (e) {
          if (e instanceof ApiError && e.kind === "unsupported") {
            return "Approving from the web app is not connected to the orchestrator yet, so nothing was paid.";
          }
          throw e;
        }
      },
      setOwner: (caseId, owner) => patchCase(caseId, { owner }),
      async testProtections() {
        const found: Protection[] = [];
        for (const caseId of ATTACK_CASES) {
          let attack;
          let saved = false;
          try {
            attack = await api.attack(caseId);
          } catch (e) {
            if (!(e instanceof ApiError && e.kind === "unsupported")) throw e;
            attack = savedAttack(caseId);
            saved = true;
          }
          found.push({ id: newId("chk"), at: new Date().toISOString(), attack, saved: saved || api.mode === "fixtures" });
        }
        setState((s) => ({ ...s, protections: [...found.reverse(), ...s.protections] }));
      },
      async saveRule(mandate, text) {
        if (api.mode === "fixtures") {
          setState((s) => ({ ...s, mandate, ruleText: text }));
          return "Saved for this tab. Sample mode replays recorded results, so new runs do not change with your rule.";
        }
        try {
          const compiled = await api.compileMandate(text);
          setState((s) => ({ ...s, mandate: compiled.mandate ?? mandate, ruleText: text }));
          return "Saved and signed. The agent uses your new rule from now on.";
        } catch (e) {
          if (e instanceof ApiError && e.kind === "unsupported") {
            return `Saving a rule from the web app is not connected to the orchestrator yet. Your signed rule ${state.mandate.mandate_id} still applies.`;
          }
          throw e;
        }
      },
      reset: () => setState(EMPTY),
    }),
    [api, state, patchCase],
  );

  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const store = useContext(Ctx);
  if (!store) throw new Error("useStore outside StoreProvider");
  return store;
}
