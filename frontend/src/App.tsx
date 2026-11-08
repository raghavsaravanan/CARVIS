import { FormEvent, useMemo, useState } from "react";

type VisionResult = {
  session_id: string;
  vehicle?: { year: string; make: string; model: string };
  component?: {
    component: string;
    confidence: number;
    visual_context: string;
    uncertainty: string;
  };
  answer?: string;
  source?: string;
  source_grounded?: boolean;
  error?: string;
};

const API_BASE = (import.meta.env.VITE_CARVIS_API_URL || "/api").replace(/\/$/, "");

function App() {
  const [photo, setPhoto] = useState<File | null>(null);
  const [question, setQuestion] = useState("What is the torque specification for this component?");
  const [year, setYear] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [transmission, setTransmission] = useState("");
  const [result, setResult] = useState<VisionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionId] = useState(() => crypto.randomUUID());
  const previewUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : ""), [photo]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setResult(null);
    if (!photo) {
      setError("Capture or select a JPEG first.");
      return;
    }
    setBusy(true);
    const body = new FormData();
    body.append("file", photo);
    body.append("question", question);
    body.append("year", year);
    body.append("make", make);
    body.append("model", model);
    if (transmission) body.append("transmission", transmission);
    body.append("session_id", sessionId);
    try {
      const response = await fetch(`${API_BASE}/vision-query`, { method: "POST", body });
      const payload = (await response.json()) as VisionResult;
      if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
      setResult(payload);
      if (payload.source_grounded && payload.answer && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(payload.answer));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Vision query failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header>
        <p className="eyebrow">CARVIS / VISION QUERY</p>
        <h1>Look at the part. Ask the manual.</h1>
        <p className="lede">A small vertical slice for the glasses workflow: JPEG context in, manual-backed answer out.</p>
      </header>

      <form className="workspace" onSubmit={submit}>
        <section className="card capture-card">
          <div className="section-heading"><span>01</span><h2>Capture context</h2></div>
          <label className="dropzone">
            {previewUrl ? <img src={previewUrl} alt="Selected vehicle component" /> : <span>Choose a JPEG from the iPhone or computer</span>}
            <input type="file" accept="image/jpeg" capture="environment" onChange={(event) => setPhoto(event.target.files?.[0] || null)} />
          </label>
          <label>Question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} /></label>
        </section>

        <section className="card">
          <div className="section-heading"><span>02</span><h2>Confirm vehicle</h2></div>
          <p className="hint">Visual identification never replaces these manual-selection fields.</p>
          <div className="vehicle-grid">
            <label>Year<input value={year} onChange={(event) => setYear(event.target.value)} placeholder="e.g. 2022" /></label>
            <label>Make<input value={make} onChange={(event) => setMake(event.target.value)} placeholder="e.g. subaru" /></label>
            <label>Model<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="e.g. wrx" /></label>
            <label>Transmission<select value={transmission} onChange={(event) => setTransmission(event.target.value)}>
              <option value="">Confirm when required</option>
              <option value="6mt">6MT</option>
              <option value="cvt">CVT</option>
            </select></label>
          </div>
          <button disabled={busy}>{busy ? "Reading manual…" : "Ask Carvis"}</button>
          {error && <p className="error">{error}</p>}
        </section>
      </form>

      <section className="card result-card" aria-live="polite">
        <div className="section-heading"><span>03</span><h2>Answer</h2></div>
        {!result && !busy && <p className="empty">Your source-grounded result will appear here.</p>}
        {busy && <p className="empty">Identifying the component, then searching the matching manual…</p>}
        {result?.component && <div className="component"><strong>{result.component.component}</strong><span>{Math.round(result.component.confidence * 100)}% visual confidence</span><p>{result.component.visual_context}</p></div>}
        {result?.answer && <blockquote>{result.answer}</blockquote>}
        {result?.source_grounded && <p className="source">✓ {result.source}</p>}
      </section>
    </main>
  );
}

export default App;
