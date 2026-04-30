const API_BASE_URL = getApiBaseUrl();

const page = document.body.dataset.page;

if (page === "register" || page === "index") {
  setupAuthPage();
}

if (page === "chat") {
  setupChatPage();
}

function setStatus(message, type) {
  const statusElement = document.querySelector("#status, #chat-status");
  if (!statusElement) {
    return;
  }

  statusElement.textContent = message;
  statusElement.className = `status ${type}`.trim();
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function getApiBaseUrl() {
  const { protocol, hostname } = window.location;

  if (protocol === "file:") {
    return "http://127.0.0.1:8000";
  }

  return `/api`;
}

function setupAuthPage() {
  const form = document.querySelector("#auth-form");
  const statusElement = document.querySelector("#status");

  if (!form || !statusElement) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();



    const submitButton = form.querySelector("button");
    const formData = new FormData(form);

    if (page === "register") {
      const password = formData.get("password");
      const confirmationPassword = formData.get("confirmationPassword");
      if (password !== confirmationPassword) {
        setStatus("Passwords do not match.", "error");
        return;
      }
    }
    const payload = {
      email: formData.get("email"),
      password: formData.get("password"),
    };

    setStatus("Working...", "");
    submitButton.disabled = true;

    try {
      const response = await fetch(`${API_BASE_URL}/${page}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        setStatus(data.detail || data.message || "Request failed.", "error");
        return;
      }

      setStatus(data.message || `${capitalize(page)} successful.`, "success");

      if (page === "register") {
        form.reset();
        window.location.href = "./index.html";
      }

      if (page === "index") {
        window.location.href = "./chat.html";
      }
    } catch (error) {
      setStatus("Could not reach the backend. Make sure the FastAPI server is running.", "error");
    } finally {
      submitButton.disabled = false;
    }
  });
}

async function setupChatPage() {
  const chatForm = document.querySelector("#chat-form");
  const promptInput = document.querySelector("#prompt");
  const chatMessages = document.querySelector("#chat-messages");
  const userEmail = document.querySelector("#user-email");
  const logoutButton = document.querySelector("#logout-button");
  const sendButton = document.querySelector("#send-button");
  const defaultSendLabel = sendButton ? sendButton.textContent : "Send";

  if (!chatForm || !promptInput || !chatMessages || !userEmail || !logoutButton || !sendButton) {
    return;
  }

  userEmail.textContent = "Loading account...";
  autoResizeTextarea(promptInput);

  promptInput.addEventListener("input", () => {
    autoResizeTextarea(promptInput);
  });

  try {
    const meResponse = await fetch(`${API_BASE_URL}/me`, {
      credentials: "include",
    });

    if (!meResponse.ok) {
      window.location.href = "./index.html";
      return;
    }

    const me = await meResponse.json();
    userEmail.textContent = me.email || "Signed-in user";

    await loadMessages(chatMessages);
  } catch (error) {
    setStatus("Could not load the chat page. Make sure the backend is running.", "error");
    return;
  }

  promptInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }

    event.preventDefault();

    try {
      chatForm.requestSubmit();
    } catch (error) {
      console.error(error);
    }
  });
  
  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const prompt = promptInput.value.trim();
    if (!prompt) {
      setStatus("Prompt cannot be empty.", "error");
      return;
    }

    promptInput.value = "";

    setStatus("Waiting for the model...", "");
    sendButton.disabled = true;
    sendButton.textContent = "Sending...";

    try {
      appendMessage(chatMessages, { role: "user", content: prompt });
      const pendingMessage = appendPendingAssistantMessage(chatMessages);

      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({ prompt }),
      });

      const data = await response.json();
      if (!response.ok) {
        pendingMessage.remove();
        removeTrailingUserMessage(chatMessages, prompt);
        promptInput.value = prompt;
        autoResizeTextarea(promptInput);
        setStatus(data.detail || "Chat request failed.", "error");
        return;
      }

      const assistantMessage = data.messages.find((message) => message.role === "assistant");
      pendingMessage.remove();
      if (assistantMessage) {
        appendMessage(chatMessages, assistantMessage);
      }
      promptInput.value = "";
      autoResizeTextarea(promptInput);
      setStatus("Reply received with conversation context.", "success");
    } catch (error) {
      removePendingAssistantMessage(chatMessages);
      removeTrailingUserMessage(chatMessages, prompt);
      promptInput.value = prompt;
      autoResizeTextarea(promptInput);
      setStatus("Could not reach the backend. Make sure the FastAPI server is running.", "error");
    } finally {
      sendButton.disabled = false;
      sendButton.textContent = defaultSendLabel;
    }
  });

  logoutButton.addEventListener("click", async () => {
    try {
      await fetch(`${API_BASE_URL}/logout`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      window.location.href = "./index.html";
    }
  });
}

async function loadMessages(chatMessages) {
  const response = await fetch(`${API_BASE_URL}/chats`, {
    credentials: "include",
  });

  if (!response.ok) {
    setStatus("Could not load chat history.", "error");
    return;
  }

  const data = await response.json();
  replaceMessages(chatMessages, data.messages);
}

function replaceMessages(chatMessages, messages) {
  chatMessages.innerHTML = "";

  if (!messages.length) {
    chatMessages.innerHTML = '<div class="empty-state">Start the conversation with your first prompt.</div>';
    return;
  }

  messages.forEach((message) => appendMessage(chatMessages, message));
}

function appendMessage(chatMessages, message) {
  const emptyState = chatMessages.querySelector(".empty-state");
  if (emptyState) {
    emptyState.remove();
  }

  const messageElement = document.createElement("article");
  messageElement.className = `message-bubble ${message.role}`;
  messageElement.dataset.role = message.role;
  messageElement.dataset.content = message.content;

  const roleElement = document.createElement("p");
  roleElement.className = "message-role";
  roleElement.textContent = message.role === "assistant" ? "Model" : "You";

  const contentElement = document.createElement("p");
  contentElement.className = "message-content";
  contentElement.textContent = message.content;

  messageElement.appendChild(roleElement);
  messageElement.appendChild(contentElement);
  chatMessages.appendChild(messageElement);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendPendingAssistantMessage(chatMessages) {
  const pendingElement = document.createElement("article");
  pendingElement.className = "message-bubble assistant pending";
  pendingElement.dataset.pending = "true";

  const roleElement = document.createElement("p");
  roleElement.className = "message-role";
  roleElement.textContent = "Model";

  const contentElement = document.createElement("div");
  contentElement.className = "typing-dots";
  contentElement.setAttribute("aria-label", "Model is thinking");
  contentElement.innerHTML = "<span></span><span></span><span></span>";

  pendingElement.appendChild(roleElement);
  pendingElement.appendChild(contentElement);
  chatMessages.appendChild(pendingElement);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return pendingElement;
}

function removePendingAssistantMessage(chatMessages) {
  const pendingElement = chatMessages.querySelector('[data-pending="true"]');
  if (pendingElement) {
    pendingElement.remove();
  }
}

function removeTrailingUserMessage(chatMessages, prompt) {
  const messages = Array.from(chatMessages.querySelectorAll(".message-bubble"));
  const lastMessage = messages[messages.length - 1];

  if (
    lastMessage &&
    lastMessage.dataset.role === "user" &&
    lastMessage.dataset.content === prompt
  ) {
    lastMessage.remove();
  }

  if (!chatMessages.children.length) {
    replaceMessages(chatMessages, []);
  }
}

function autoResizeTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
}
