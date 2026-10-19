import { Shell } from "./components/Shell";
import { Activity } from "./pages/Activity";
import { GetCash } from "./pages/GetCash";
import { Home } from "./pages/Home";
import { Invoice } from "./pages/Invoice";
import { Invoices } from "./pages/Invoices";
import { NeedsYou } from "./pages/NeedsYou";
import { Rule } from "./pages/Rule";
import { useRoute } from "./router";

const TITLES: Record<string, string> = {
  "": "Home",
  "get-cash": "Get cash",
  invoice: "Invoice",
  invoices: "Invoices",
  "needs-you": "Needs you",
  rule: "My rule",
  activity: "Money & activity",
};

export function App() {
  const [page = "", id] = useRoute();
  const known = page in TITLES;
  document.title = `${known ? TITLES[page] : "Not found"} · ReceivableOS`;
  return (
    <Shell page={page}>
      {page === "" && <Home />}
      {page === "get-cash" && <GetCash key={id ?? "new"} />}
      {page === "invoice" && <Invoice id={id} />}
      {page === "invoices" && <Invoices />}
      {page === "needs-you" && <NeedsYou />}
      {page === "rule" && <Rule />}
      {page === "activity" && <Activity />}
      {!known && (
        <section className="card empty">
          <h1 tabIndex={-1}>Page not found</h1>
          <a className="btn btn-primary" href="#/">
            Go home
          </a>
        </section>
      )}
    </Shell>
  );
}
