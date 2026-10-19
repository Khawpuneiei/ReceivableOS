import { advance, type Case, status } from "../model";
import { day, money, when } from "../money";
import { Link } from "../router";
import { Chip } from "./ui";

export function CaseTable({ cases }: { cases: Case[] }) {
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">Invoice</th>
            <th scope="col">Buyer</th>
            <th scope="col" className="num">
              Amount
            </th>
            <th scope="col">Due</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              You got
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const s = status(c);
            const inv = c.flow.ocr;
            const got = s.key === "funded" || s.key === "paid" ? advance(c.flow) : null;
            return (
              <tr key={c.id}>
                <td>
                  <Link to={`/invoice/${c.id}`}>
                    <b>{inv.invoice_no}</b>
                  </Link>
                  <small>Uploaded {when(c.at)}</small>
                </td>
                <td style={{ whiteSpace: "normal", minWidth: 140 }}>{inv.buyer.name}</td>
                <td className="num">
                  <b>{money(inv.amount, inv.currency)}</b>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>{day(inv.due_date)}</td>
                <td>
                  <Chip tone={s.tone}>{s.label}</Chip>
                </td>
                <td className="num">{got === null ? <span className="muted">{money(0n)}</span> : <b>{money(got)}</b>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
