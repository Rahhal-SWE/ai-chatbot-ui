document.getElementById("send-btn").addEventListener("click", sendMessage);

async function sendMessage() {
  const inputField = document.getElementById("user-input");
  const message = inputField.value.trim();
  if (!message) return;

  appendMessage("You", message);
  inputField.value = "";
  appendMessage("Bot", "Typing...");

  const response = await getChatGPTReply(message);
  updateLastBotMessage(response);
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
}

function updateLastBotMessage(text) {
  const chatWindow = document.getElementById("chat-window");
  const messages = chatWindow.querySelectorAll("div");
  const lastMessage = messages[messages.length - 1];
  lastMessage.innerText = `Bot: ${text}`;
}

// ⚠️ Replace this function to call OpenAI API next
async function getChatGPTReply(message) {
  return "This will be replaced with a real API call!";
}
