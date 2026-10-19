import { type Case, status } from "../model";
import { money } from "../money";
import { Link } from "../router";
import { Chip } from "./ui";

/** A short list of invoices for a narrow column: number, buyer and amount, then the status. */
export function CaseList({ cases }: { cases: Case[] }) {
  return (
    <ul className="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {cases.map((c) => {
        const s = status(c);
        const inv = c.flow.ocr;
        return (
          <li key={c.id} className="item">
            <div className="what">
              <Link to={`/invoice/${c.id}`}>
                <b>{inv.invoice_no}</b>
              </Link>
              <div>
                {inv.buyer.name} · {money(inv.amount, inv.currency)}
              </div>
            </div>
            <Chip tone={s.tone}>{s.label}</Chip>
          </li>
        );
      })}
    </ul>
  );
}
