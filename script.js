// =========================
// Config
// =========================
// =========================
// Config
// =========================
// Auto switch:
// - Local dev: Flask on http://127.0.0.1:5000
// - Deployed frontend (GitHub Pages): backend on Render (https)
const API_BASE = "";

// =========================
// UI wiring
// =========================
document.getElementById("send-btn").addEventListener("click", sendMessage);
document.getElementById("user-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

async function sendMessage() {
  const inputField = document.getElementById("user-input");
  const message = inputField.value.trim();
  if (!message) return;

  appendMessage("You", message);
  inputField.value = "";

  // Create bot message element that we update live
  const botEl = appendMessage("Bot", "");

  try {
    const result = await getChatGPTReply(message);

    // Non-stream response (e.g., JSON error)
    if (result.mode === "full") {
      botEl.innerText = `Bot: ${result.text}`;
      return;
    }

    botEl.innerText = "Bot: ";
    await result.pump((_chunk, fullText) => {
      botEl.innerText = `Bot: ${fullText}`;
    });
  } catch (err) {
    botEl.innerText = `Bot: Error: ${String(err)}`;
  }
}

function appendMessage(sender, text) {
  const chatWindow = document.getElementById("chat-window");

  const messageEl = document.createElement("div");
  messageEl.className = `my-2 p-2 rounded ${
    sender === "You" ? "bg-blue-100 text-right" : "bg-gray-200"
  }`;

  messageEl.innerText = `${sender}: ${text}`;
  chatWindow.appendChild(messageEl);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  return messageEl; // important: return DOM node so we can update it
}

// =========================
// Streaming API call (SSE over fetch)
// =========================
async function getChatGPTReply(message) {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  // If backend returns JSON error, show it nicely
  const contentType = res.headers.get("content-type") || "";
  if (!res.ok) {
    if (contentType.includes("application/json")) {
      const data = await res.json();
      return {
        mode: "full",
        text: data.error ? `Error: ${data.error}` : "Server error.",
      };
    }
    return { mode: "full", text: `Server error (${res.status})` };
  }

  // If backend didn't return SSE, fall back to reading JSON/text
  if (!contentType.includes("text/event-stream")) {
    if (contentType.includes("application/json")) {
      const data = await res.json();
      return { mode: "full", text: data.reply || JSON.stringify(data) };
    }
    const txt = await res.text();
    return { mode: "full", text: txt };
  }

  // Stream SSE lines from fetch body
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");

  let buffer = "";
  let fullText = "";

  return {
    mode: "stream",
    async pump(onChunk) {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE events are separated by blank line
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const event of events) {
          const line = event.trim();
          if (!line.startsWith("data:")) continue;

          const data = line.slice(5).trim();
          if (data === "[DONE]") return fullText;

          fullText += data;
          onChunk(data, fullText);
        }
      }
      return fullText;
    },
  };
}
