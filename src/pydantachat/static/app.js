// One page, one form, one streaming fetch. No framework, no build step.
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const form = document.getElementById("composer");
const input = document.getElementById("message");
const newButton = document.getElementById("new");
const signInCard = document.getElementById("sign-in-card");

const STATUS_MESSAGES = {
  400: "the request was rejected",
  401: "session expired — sign in again",
  403: "this account is not allowed",
  422: "that message is too long",
  502: "the provider failed; try again",
  503: "the server is not ready yet",
};

const LABELS = { you: "you", bot: "pydantachat", system: "system" };

let sessionId = null;

// textContent, never innerHTML: replies are untrusted.
function line(kind, text) {
  const article = document.createElement("article");
  article.className = kind;

  const header = document.createElement("header");
  const label = document.createElement("small");
  label.textContent = LABELS[kind] || kind;
  header.append(label);

  const body = document.createElement("p");
  body.textContent = text;

  article.append(header, body);
  logEl.append(article);
  article.scrollIntoView({ block: "nearest" });
  return article;
}

// Deltas arrive as they are generated; the first one replaces the ellipsis.
function appendText(article, text) {
  const body = article.querySelector("p");
  if (body.textContent === "…") body.textContent = "";
  body.textContent += text;
}

// The API sends `event: <name>` + `data: <json>` frames, then `data: [DONE]`.
function consume(buffer, article) {
  const frames = buffer.split("\n\n");
  const rest = frames.pop();

  for (const frame of frames) {
    let event = "message";
    const data = [];
    for (const raw of frame.split("\n")) {
      if (raw.startsWith("event: ")) event = raw.slice("event: ".length).trim();
      else if (raw.startsWith("data: ")) data.push(raw.slice("data: ".length));
    }
    if (data.length === 0) continue;

    const payload = data.join("\n");
    if (event === "session") {
      sessionId = JSON.parse(payload).session_id;
    } else if (event === "error") {
      line("system", "the provider failed; try again");
    } else if (payload === "[DONE]") {
      // Visible to the smoke test, and a truthful signal for the page itself.
      article.dataset.done = "1";
    } else {
      appendText(article, JSON.parse(payload).text ?? "");
    }
  }
  return rest;
}

function link(href, text) {
  const a = document.createElement("a");
  a.href = href;
  a.textContent = text;
  return a;
}

async function whoAmI() {
  const response = await fetch("/api/me", { credentials: "same-origin" });
  const signedIn = response.ok;

  // Nothing chat-related renders without a session: no empty transcript, no box.
  form.hidden = !signedIn;
  logEl.hidden = !signedIn;
  signInCard.hidden = signedIn;

  if (!signedIn) {
    statusEl.replaceChildren("signed out");
    return;
  }
  const user = await response.json();
  statusEl.replaceChildren(`${user.email} · `, link("/logout", "logout"));
}

function showSystem(message) {
  line("system", message);
}

// Enter sends; Shift+Enter is a newline.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newButton.addEventListener("click", () => {
  sessionId = null;
  logEl.replaceChildren();
  input.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  line("you", message);
  input.value = "";
  const answerEl = line("bot", "…");
  input.focus();

  let response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
  } catch {
    answerEl.remove();
    showSystem("network error");
    return;
  }

  if (!response.ok) {
    answerEl.remove();
    showSystem(
      STATUS_MESSAGES[response.status] || `request failed (${response.status})`,
    );
    if (response.status === 401) whoAmI();
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = consume(buffer, answerEl);
  }
});

whoAmI();
