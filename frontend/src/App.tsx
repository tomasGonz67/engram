import "./App.css";

function App() {
  return (
    <div id="app">
      <header id="header">
        <h2>Engram</h2>
        <p>A biologically inspired memory system for AI</p>
      </header>

      <div id="body">
        <section id="chat-panel">
          <div id="chat-history"></div>
          <div id="chat-input">
            <input type="text" placeholder="Ask Engram something..." />
            <button type="button">Send</button>
          </div>
        </section>

        <section id="analytics-panel">
          <div id="analytics-history">Analytics history</div>
        </section>
      </div>
    </div>
  );
}

export default App;
