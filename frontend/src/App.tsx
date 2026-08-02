import { useState } from "react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Sliding window: only the most recent messages get sent as context, not
// the whole conversation. At this project's usage scale it's not about
// cost (negligible either way) — it's avoiding "lost in the middle"
// quality degradation on long conversations and staying nowhere near
// GPT-5.4 Nano's 400K token context ceiling.
const RECENT_TURNS_LIMIT = 20;

// Mirrors backend/constants.py's SEMANTIC_THRESHOLD — not returned by the
// API (it's a fixed config value, not per-request data), so hardcoded here
// purely for display in the analytics modal.
const SEMANTIC_THRESHOLD = 0.75;

type Turn = {
  role: "user" | "assistant";
  content: string;
};

type RetrievedMemory = {
  id: string;
  text: string;
  semantic: number;
  retrievability: number;
  frequency: number;
  final_score: number;
  stability: number;
  use_count: number;
  age_days: number;
  impact: number;
};

type AnalyticsEntry = {
  query: string;
  retrieved: RetrievedMemory[];
  reinforcedIds: string[];
};

// Guards the modal's stat rendering against a field that's missing or the
// wrong type — no known way to trigger this today, purely defensive against
// an unexpected /generate response shape.
function safeToFixed(value: unknown, decimals: number): string {
  return typeof value === "number" ? value.toFixed(decimals) : "?";
}

const ABOUT_TEXT =
  "Masi Memory is a biologically inspired memory system for AI — a simplified " +
  "model of human memory that incorporates real cognitive science " +
  "principles (decay, reinforcement, consolidation) into practical " +
  "algorithms for long-term AI memory, instead of just storing and " +
  "replaying text verbatim.";

const FORMULAS = [
  { name: "Impact (set at creation)", formula: "impact = clamp(provided_impact, 0.5, 2.0)" },
  { name: "Initial stability (at creation)", formula: "stability = BASE_STABILITY × impact" },
  { name: "Semantic similarity", formula: "semantic = (raw_cosine_similarity + 1) / 2" },
  { name: "Age", formula: "age_days = days since last_reinforced_at" },
  { name: "Retrievability (computed live, never stored)", formula: "retrievability = (1 + age_days / stability) ^ -0.5" },
  { name: "Use count", formula: "use_count += 1 (on each confirmed reinforcement)" },
  { name: "Frequency", formula: "frequency = 1 - exp(-use_count / 5)" },
  { name: "Ranking score", formula: "final_score = 0.75×semantic + 0.15×retrievability + 0.10×frequency" },
  { name: "On reinforcement", formula: "stability = min(stability × 1.2, MAX_STABILITY)" },
];

const NEUROSCIENCE_TERMS = [
  {
    term: "impact",
    explanation: "How significant this memory seemed when first stored. Higher-impact memories resist decay longer even before being reinforced — loosely modeling how emotionally significant moments (\"flashbulb memories\") tend to be remembered more durably.",
  },
  {
    term: "stability",
    explanation: "How resistant this memory is to being forgotten. Starts based on how significant it seemed when created, and grows every time it's genuinely relied on — like a synapse strengthening from real use, not just being glanced at.",
  },
  {
    term: "semantic",
    explanation: "How closely this memory's meaning matches your question — pure vector similarity, nothing else.",
  },
  {
    term: "age_days",
    explanation: "How many days it's been since this memory was last reinforced. Feeds directly into retrievability — the longer it's been, the more retrievability decays, unless reinforcement resets the clock.",
  },
  {
    term: "retrievability",
    explanation: "How \"available\" this memory is right now, based on its stability and how long it's been since it was last used. Fades over time if untouched, modeling the brain's natural forgetting curve.",
  },
  {
    term: "use_count",
    explanation: "How many times this memory was actually relied on to answer something, not just shown as a candidate. Grounded in the \"testing effect\": genuinely using information strengthens it far more than passively re-reading it.",
  },
  {
    term: "frequency",
    explanation: "A score derived from use_count that feeds into ranking — how often this memory has proven genuinely useful.",
  },
  {
    term: "final_score",
    explanation: "The combined ranking score memories are actually sorted by — mostly semantic similarity (75%), with smaller contributions from retrievability (15%) and frequency (10%). A weighted sum rather than a product, deliberately, so one weak signal (like a brand-new, never-used memory) can't zero out an otherwise strong match.",
  },
  {
    term: "reinforcement",
    explanation: "What happens when a memory is confirmed to have actually been used, not just shown. Each reinforcement multiplies stability by 1.2× (capped at a maximum), making the memory meaningfully harder to forget going forward. Deliberately never triggered by mere retrieval — only by confirmed use — because reinforcing on exposure alone would create a self-reinforcing loop where popular memories rank higher, get shown more, get reinforced just from being seen, and rank even higher still, regardless of whether they were ever actually useful.",
  },
];

type InfoModal = "about" | "formulas" | "neuroscience" | null;

function App() {
  const [messages, setMessages] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [analyticsEntries, setAnalyticsEntries] = useState<AnalyticsEntry[]>([]);
  const [openModalIndex, setOpenModalIndex] = useState<number | null>(null);
  const [infoModal, setInfoModal] = useState<InfoModal>(null);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    const history = messages;
    setMessages([...history, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, recent_turns: history.slice(-RECENT_TURNS_LIMIT) }),
      });

      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }

      const data = await response.json();
      setMessages((current) => [...current, { role: "assistant", content: data.answer }]);
      setAnalyticsEntries((current) => [
        ...current,
        {
          query: text,
          // Guard against an unexpected response shape — falls back to
          // empty arrays rather than storing something the modal's
          // .map()/.includes() calls would later crash on.
          retrieved: Array.isArray(data.retrieved) ? data.retrieved : [],
          reinforcedIds: Array.isArray(data.reinforced_memory_ids)
            ? data.reinforced_memory_ids
            : [],
        },
      ]);
    } catch {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: "Something went wrong reaching Masi Memory." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const openEntry = openModalIndex !== null ? analyticsEntries[openModalIndex] : null;

  return (
    <div id="app">
      <header id="header">
        <div id="header-title">
          <h2>Masi Memory</h2>
          <p>A biologically inspired memory system for AI</p>
        </div>
        <div id="header-buttons">
          <button type="button" onClick={() => setInfoModal("about")}>
            About
          </button>
          <button type="button" onClick={() => setInfoModal("formulas")}>
            Formulas
          </button>
          <button type="button" onClick={() => setInfoModal("neuroscience")}>
            Terms
          </button>
        </div>
      </header>

      <div id="body">
        <section id="chat-panel">
          <div id="chat-history">
            {messages.map((m, i) => (
              <div key={i} className={`message ${m.role}`}>
                {m.content}
              </div>
            ))}
            {loading && <div className="message assistant">...</div>}
          </div>
          <form id="chat-input" onSubmit={sendMessage}>
            <input
              type="text"
              placeholder="Ask Masi Memory something..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <button type="submit" disabled={loading}>
              Send
            </button>
          </form>
        </section>

        <section id="analytics-panel">
          <div id="analytics-history">
            {analyticsEntries.map((entry, i) => (
              <div className="analytics-card" key={i}>
                <p>Analytics for message: "{entry.query}"</p>
                <button type="button" onClick={() => setOpenModalIndex(i)}>
                  Show Analytics
                </button>
              </div>
            ))}
          </div>
        </section>
      </div>

      {openEntry && (
        <div className="modal-backdrop" onClick={() => setOpenModalIndex(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Analytics</h3>
              <button
                type="button"
                className="modal-close"
                onClick={() => setOpenModalIndex(null)}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <p className="threshold-note">
                Semantic threshold: {SEMANTIC_THRESHOLD}
              </p>
              {openEntry.retrieved.length === 0 && (
                <p>No memories retrieved for this message.</p>
              )}
              {openEntry.retrieved.map((m) => (
                <div className="memory-row" key={m.id}>
                  <p className="memory-text">"{m.text}"</p>
                  <div className="memory-scores">
                    <span>stability: {safeToFixed(m.stability, 2)}</span>
                    <span>use_count: {typeof m.use_count === "number" ? m.use_count : "?"}</span>
                    <span>age_days: {safeToFixed(m.age_days, 2)}</span>
                    <span>impact: {safeToFixed(m.impact, 2)}</span>
                  </div>
                  <div className="memory-scores">
                    <span>semantic: {safeToFixed(m.semantic, 2)}</span>
                    <span>retrievability: {safeToFixed(m.retrievability, 2)}</span>
                    <span>frequency: {safeToFixed(m.frequency, 2)}</span>
                  </div>
                  <div className="memory-final-row">
                    <span>final_score: {safeToFixed(m.final_score, 2)}</span>
                    {openEntry.reinforcedIds.includes(m.id) && (
                      <span className="reinforced-tag">reinforced</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {infoModal && (
        <div className="modal-backdrop" onClick={() => setInfoModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {infoModal === "about" && "About"}
                {infoModal === "formulas" && "Formulas"}
                {infoModal === "neuroscience" && "Terms"}
              </h3>
              <button type="button" className="modal-close" onClick={() => setInfoModal(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              {infoModal === "about" && <p>{ABOUT_TEXT}</p>}

              {infoModal === "formulas" &&
                FORMULAS.map((f) => (
                  <div className="info-row" key={f.name}>
                    <p className="info-term">{f.name}</p>
                    <code>{f.formula}</code>
                  </div>
                ))}

              {infoModal === "neuroscience" &&
                NEUROSCIENCE_TERMS.map((t) => (
                  <div className="info-row" key={t.term}>
                    <p className="info-term">{t.term}</p>
                    <p>{t.explanation}</p>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
