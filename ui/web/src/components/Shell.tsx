import type { ReactNode } from "react";
import { totals } from "../model";
import { Link } from "../router";
import { useStore } from "../store";
import { Icon, type IconName } from "./Icon";

const NAV: { to: string; page: string; label: string; short: string; icon: IconName; phone: boolean }[] = [
  { to: "/", page: "", label: "Home", short: "Home", icon: "home", phone: true },
  { to: "/get-cash", page: "get-cash", label: "Get cash", short: "Get cash", icon: "upload", phone: true },
  { to: "/invoices", page: "invoices", label: "Invoices", short: "Invoices", icon: "invoice", phone: true },
  { to: "/needs-you", page: "needs-you", label: "Needs you", short: "Needs you", icon: "bell", phone: true },
  { to: "/rule", page: "rule", label: "My rule", short: "Rule", icon: "rule", phone: false },
  { to: "/activity", page: "activity", label: "Money & activity", short: "Money", icon: "wallet", phone: true },
];

export function Shell({ page, children }: { page: string; children: ReactNode }) {
  const { state, api } = useStore();
  const { needsYou } = totals(state.cases, state.protections);
  const active = page === "invoice" ? "invoices" : page;
  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="rail">
      <aside className="side">
        <Link to="/" className="logo">
          <span aria-hidden="true">R</span>ReceivableOS
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`${n.page === active ? "on" : ""}${n.phone ? "" : " desk"}`} aria-current={n.page === active ? "page" : undefined}>
              <Icon name={n.icon} />
              <span className="long">{n.label}</span>
              <span className="short">{n.short}</span>
              {n.page === "needs-you" && needsYou > 0 && (
                <span className="badge" aria-label={`${needsYou} waiting`}>
                  {needsYou}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="who">
          <span aria-hidden="true">S</span>
          <div>
            <b>Siam Fresh Pack Co., Ltd.</b>
            <small>Verified business</small>
          </div>
        </div>
      </aside>
      </div>
      <div className="body">
        <header className="mtop">
          <Link to="/" className="logo">
            <span aria-hidden="true">R</span>ReceivableOS
          </Link>
          <Link to="/rule" className="mrule">
            <Icon name="rule" />
            My rule
          </Link>
        </header>
        {api.mode === "fixtures" && (
          <div className="mode" role="note">
            Sample mode: the app replays responses recorded from the live stack. Nothing is sent anywhere.
          </div>
        )}
        <main id="main" className="main">
          <div className="wrap">{children}</div>
        </main>
      </div>
    </div>
  );
}
