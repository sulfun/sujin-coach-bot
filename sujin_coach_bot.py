// ─────────────────────────────────────────────
// Paste/integrate into sujinos.netlify.app dashboard JS.
// Two integration points:
//   1) On dashboard load → pullPendingTasks() to merge bot-pushed memos
//   2) On task save     → notifyTaskSaved(text, time) to ping Telegram
// ─────────────────────────────────────────────

const BRIDGE = "/api/tg-bridge";
// IMPORTANT: this token is stored in localStorage so the dashboard JS
// can call the bridge from the browser. Treat it as a shared secret —
// rotate by changing BRIDGE_TOKEN in Netlify env + Railway env together.
const BRIDGE_TOKEN = localStorage.getItem("METIS_BRIDGE_TOKEN") || "";

async function bridgeFetch(path, opts = {}) {
  return fetch(BRIDGE + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Token": BRIDGE_TOKEN,
      ...(opts.headers || {}),
    },
  });
}

// 1) On dashboard load — merge bot-pushed memos into today's task list
async function pullPendingTasks() {
  if (!BRIDGE_TOKEN) return [];
  try {
    const r = await bridgeFetch("?action=dashboard_pull");
    if (!r.ok) return [];
    const { tasks } = await r.json();
    // tasks: [{text, tag, ts}, ...]
    // TODO: merge into your localStorage today's tasks structure here.
    // Example:
    //   const today = JSON.parse(localStorage.getItem("today") || "[]");
    //   tasks.forEach(t => today.push({title: t.text, tag: t.tag, from: "telegram"}));
    //   localStorage.setItem("today", JSON.stringify(today));
    //   renderTodayTasks();
    return tasks;
  } catch (e) {
    console.warn("pullPendingTasks failed", e);
    return [];
  }
}

// 2) On task save — tell the bot so it can send evening confirmation
async function notifyTaskSaved(text, time = "") {
  if (!BRIDGE_TOKEN) return;
  try {
    await bridgeFetch("?action=task_saved", {
      method: "POST",
      body: JSON.stringify({ text, time }),
    });
  } catch (e) {
    console.warn("notifyTaskSaved failed", e);
  }
}

// Optional: send arbitrary message to Telegram immediately
async function tgSend(text) {
  if (!BRIDGE_TOKEN) return;
  try {
    await bridgeFetch("?action=tg_send", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  } catch (e) {
    console.warn("tgSend failed", e);
  }
}

// Bootstrap
window.addEventListener("DOMContentLoaded", () => {
  pullPendingTasks();
  // Optional: re-poll every 60s while dashboard is open
  setInterval(pullPendingTasks, 60_000);
});
