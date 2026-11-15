// One page, one form, one streaming fetch. No framework, no build step.
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const form = document.getElementById("composer");
const input = document.getElementById("message");
const newButton = document.getElementById("new");

const STATUS_MESSAGES = {
  400: "the request was rejected",
  401: "session expired — sign in again",
  403: "this account is not allowed",
  422: "that message is too long",
  502: "the provider failed; try again",
  503: "the server is not ready yet",
};

let sessionId = null;

// textContent, never innerHTML: replies are untrusted.
function line(kind, text) {
  const li = document.createElement("li");
  li.className = kind;
  li.append(document.createElement("span"));
  li.querySelector("span").textContent = text;
  logEl.append(li);
  li.scrollIntoView();
  return li;
}

function renderAnswer(li, answer) {
  const body = li.querySelector("span");
  if (typeof answer.number !== "number" || typeof answer.is_even !== "boolean") {
    body.textContent = "…";
    return;
  }
  body.textContent = `${answer.number} is ${answer.is_even ? "even" : "odd"}.`;

  let reasoning = li.querySelector(".reasoning");
  if (answer.reasoning) {
    if (!reasoning) {
      reasoning = document.createElement("em");
      reasoning.className = "reasoning";
      li.append(reasoning);
    }
    reasoning.textContent = answer.reasoning;
  }
}

// The API sends `event: <name>` + `data: <json>` frames, then `data: [DONE]`.
function consume(buffer, li) {
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
    } else if (payload !== "[DONE]") {
      renderAnswer(li, JSON.parse(payload));
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
  // Nothing chat-related renders without a session: no empty transcript, no box.
  form.hidden = !response.ok;
  logEl.hidden = !response.ok;
  if (!response.ok) {
    statusEl.replaceChildren("signed out · ", link("/login", "sign in"));
    return;
  }
  const user = await response.json();
  statusEl.replaceChildren(`${user.email} · `, link("/logout", "logout"));
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
    line("system", "network error");
    return;
  }

  if (!response.ok) {
    answerEl.remove();
    line(
      "system",
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
