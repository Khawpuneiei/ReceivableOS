import { shortRef } from "./flow";
import { Dot } from "./ui";
import type { Event } from "../model";
import { money, when } from "../money";

/** compact: no time or receipt, for a narrow column. */
export function Events({ events, empty, compact }: { events: Event[]; empty: string; compact?: boolean }) {
  if (events.length === 0) return <p className="help">{empty}</p>;
  return (
    <ul className="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {events.map((e) => (
        <li key={e.id} className="item">
          <Dot tone={e.tone} />
          <div className="what">
            <b>{e.title}</b>
            <div>{compact ? e.detail : `${when(e.at)} · ${e.detail}`}</div>
          </div>
          {e.amount !== undefined && (
            <span className={`amt${e.tone === "ok" ? " good" : ""}`}>
              {e.tone === "ok" ? "+ " : ""}
              {money(e.amount)}
            </span>
          )}
          {e.receipt && !compact && (
            <span className="rcpt" title={e.receipt}>
              {shortRef(e.receipt)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
