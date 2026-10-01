/** Turn shaping for the operator chat panel.
 *
 *  Kept apart from the component so it is testable: the client has no jsdom or
 *  testing-library, and every existing test is pure logic.
 */

export type ChatRole = "user" | "assistant" | "system";

export type ChatTurn = {
  id: string;
  role: ChatRole;
  text: string;
  agent: string;
};

/** One message as conversation_memory.get_session_messages returns it. */
type ServerMessage = {
  event_id?: unknown;
  role?: unknown;
  text?: unknown;
  agent?: unknown;
};

export type ChatReply = {
  status?: unknown;
  error?: unknown;
  error_type?: unknown;
  session_id?: unknown;
  messages?: unknown;
  result?: { response?: unknown; error?: unknown } | null;
};

const ROLES: ChatRole[] = ["user", "assistant", "system"];

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Server history is authoritative, so other surfaces' turns show up here too.
 *  Blank-text events are dropped: the spine records some events with no body. */
export function turnsFrom(reply: ChatReply): ChatTurn[] {
  const messages = Array.isArray(reply.messages)
    ? (reply.messages as ServerMessage[])
    : [];
  const turns: ChatTurn[] = [];
  messages.forEach((message, index) => {
    const body = text(message?.text).trim();
    if (!body) return;
    const role = ROLES.includes(message?.role as ChatRole)
      ? (message?.role as ChatRole)
      : "assistant";
    turns.push({
      id: text(message?.event_id) || `turn-${index}`,
      role,
      text: body,
      agent: text(message?.agent) || "daise",
    });
  });
  return turns;
}

/** What the operator is told when a send does not produce a visible answer.
 *  Empty string means the reply stands on its own and needs no notice. */
export function noticeFrom(reply: ChatReply): string {
  if (reply.error_type === "session_busy")
    return "Another surface is mid-turn on this session. Wait for it to finish, then send again.";
  const failure = text(reply.error) || text(reply.result?.error);
  if (reply.status === "error") return failure || "That turn did not complete.";
  if (failure) return failure;
  return "";
}

/** The session to send with the next message. Keeps the turn on the operator's
 *  shared session rather than starting a new one per message. */
export function sessionFrom(reply: ChatReply, current: string): string {
  return text(reply.session_id) || current;
}

/** True when the reply produced nothing to render, so the panel can say so
 *  instead of looking like it silently dropped the message. */
export function isSilent(reply: ChatReply): boolean {
  return !turnsFrom(reply).length && !text(reply.result?.response).trim();
}
