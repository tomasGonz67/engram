import { useState } from "react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Sliding window: only the most recent messages get sent as context, not
// the whole conversation. At this project's usage scale it's not about
// cost (negligible either way) — it's avoiding "lost in the middle"
// quality degradation on long conversations and staying nowhere near
// GPT-5.4 Nano's 400K token context ceiling.
const RECENT_TURNS_LIMIT = 20;

type Turn = {
  role: "user" | "assistant";
  content: string;
};

function App() {
  const [messages, setMessages] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

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
    } catch {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: "Something went wrong reaching Engram." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div id="app">
      <header id="header">
        <h2>Engram</h2>
        <p>A biologically inspired memory system for AI</p>
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
              placeholder="Ask Engram something..."
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
            <div className="analytics-card">
              <p>Analytics for message: "what was the last thing you said?"</p>
              <button type="button" onClick={() => setShowModal(true)}>
                Show Analytics
              </button>
            </div>
          </div>
        </section>
      </div>

      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Analytics</h3>
              <button type="button" className="modal-close" onClick={() => setShowModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="memory-row">
                <p className="memory-text">"Met my girlfriend playing Toontown years ago"</p>
                <span className="reinforced-tag">reinforced</span>
                <div className="memory-scores">
                  <span>semantic: 0.81</span>
                  <span>retrievability: 0.99</span>
                  <span>frequency: 0.33</span>
                  <span>final_score: 0.79</span>
                </div>
              </div>
              <div className="memory-row">
                <p className="memory-text">"Played Roblox with my girlfriend for hours today"</p>
                <div className="memory-scores">
                  <span>semantic: 0.76</span>
                  <span>retrievability: 0.96</span>
                  <span>frequency: 0.18</span>
                  <span>final_score: 0.72</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
