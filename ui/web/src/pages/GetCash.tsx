import { useState, type DragEvent } from "react";
import { type Sample, SAMPLES } from "../api";
import { Checks } from "../components/flow";
import { Icon } from "../components/Icon";
import { Section, Steps } from "../components/ui";
import { go } from "../router";
import { useStore } from "../store";

const ACCEPT = ".pdf,.png,.jpg,.jpeg";

export function GetCash() {
  const store = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  async function run(load: () => Promise<Blob>, filename: string) {
    setBusy(filename);
    setError(null);
    try {
      const c = await store.run(await load(), filename);
      go(`/invoice/${c.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const runFile = (file: File) => run(async () => file, file.name);
  // Live mode posts the demo PDF itself; sample mode only needs its name to pick the recorded run.
  const runSample = (s: Sample) =>
    run(async () => (store.api.mode === "live" ? (await fetch(s.url)).blob() : new Blob([])), s.filename);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file && !busy) void runFile(file);
  };

  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>Get cash for an invoice</h1>
          <p>Upload the invoice. We read it, check it and price it inside your rule.</p>
        </div>
      </div>
      <Steps at={busy ? 2 : 1} />

      {busy ? (
        <div className="two">
          <div className="grow">
            <section className="card" style={{ flexDirection: "row", alignItems: "center", gap: 16 }}>
              <span className="dot d-info" aria-hidden="true">
                <Icon name="file" />
              </span>
              <div style={{ flex: "1 1 auto", minWidth: 0 }}>
                <b style={{ overflowWrap: "anywhere" }}>{busy}</b>
                <div className="help">Only its fingerprint is recorded on the ledger, never the file.</div>
              </div>
            </section>
            <Section title="Checking your invoice" action={<span className="chip info">Working</span>}>
              <div role="status" className="sr">
                Checking {busy}
              </div>
              <Checks running />
            </Section>
          </div>
        </div>
      ) : (
        <>
          {error && (
            <div className="notice bad" role="alert">
              {error}
            </div>
          )}
          <label
            className={`drop${over ? " over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
          >
            <span className="dot d-info" aria-hidden="true">
              <Icon name="upload" />
            </span>
            <b>Drop your invoice here, or choose a file</b>
            <span className="help">PDF, PNG or JPG. The text inside is read as data only, never as instructions.</span>
            <span className="btn btn-primary">Choose a file</span>
            <input
              className="sr"
              type="file"
              accept={ACCEPT}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void runFile(file);
              }}
            />
          </label>
          <Section title="Or try a sample invoice">
            <p className="help">
              {store.api.mode === "live"
                ? "These are the demo PDFs, sent through the live flow."
                : "These replay runs recorded from the live flow."}{" "}
              An invoice can be financed once: trying the clean one twice is refused as a duplicate.
            </p>
            <div className="samples">
              {SAMPLES.map((s) => (
                <button key={s.id} type="button" className="sample" onClick={() => void runSample(s)}>
                  <b>{s.label}</b>
                  <span>{s.hint}</span>
                </button>
              ))}
            </div>
          </Section>
          <p className="help">If a check fails, the process stops and tells you why. Nothing is financed and nothing is signed.</p>
        </>
      )}
    </>
  );
}
