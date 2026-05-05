// Metis ↔ 수진 OS — Telegram bridge (Netlify Function, CommonJS)
//
// All endpoints require header: X-Bridge-Token: <BRIDGE_TOKEN env>
//
//   POST /.netlify/functions/tg-bridge?action=push_task
//        body: { text: string, tag?: string }
//        → push memo from bot into dashboard task queue
//
//   GET  /.netlify/functions/tg-bridge?action=dashboard_pull
//        → return queued tasks AND clear the queue
//
//   POST /.netlify/functions/tg-bridge?action=task_saved
//        body: { tasks: Array<{text,tag?,time?}|string>, time?: string }
//        → enqueue a "task_saved" event for the bot to deliver via Telegram
//
//   GET  /.netlify/functions/tg-bridge?action=bot_pull
//        → return queued events AND clear the queue (bot polls every ~1 min)

const { getStore } = require("@netlify/blobs");

const STORE_NAME = "metis-bridge";
const TASK_QUEUE_KEY = "dashboard:task_queue";
const EVENT_QUEUE_KEY = "bot:event_queue";

const json = (statusCode, body) => ({
  statusCode,
  headers: { "content-type": "application/json; charset=utf-8" },
  body: JSON.stringify(body),
});

function parseBody(event) {
  if (!event.body) return {};
  try {
    const raw = event.isBase64Encoded
      ? Buffer.from(event.body, "base64").toString("utf-8")
      : event.body;
    return JSON.parse(raw);
  } catch (_) {
    return {};
  }
}

function getHeader(headers, name) {
  if (!headers) return undefined;
  const lower = name.toLowerCase();
  for (const k of Object.keys(headers)) {
    if (k.toLowerCase() === lower) return headers[k];
  }
  return undefined;
}

async function readQueue(store, key) {
  const v = await store.get(key, { type: "json" });
  return Array.isArray(v) ? v : [];
}

async function clearQueue(store, key) {
  await store.setJSON(key, []);
}

exports.handler = async (event) => {
  const expected = process.env.BRIDGE_TOKEN;
  if (!expected) return json(500, { error: "BRIDGE_TOKEN not set" });

  const provided = getHeader(event.headers, "x-bridge-token");
  if (provided !== expected) return json(401, { error: "unauthorized" });

  const action = (event.queryStringParameters || {}).action;
  const method = event.httpMethod;
  const store = getStore(STORE_NAME);

  try {
    if (action === "push_task" && method === "POST") {
      const body = parseBody(event);
      const text = typeof body.text === "string" ? body.text.trim() : "";
      if (!text) return json(400, { error: "text required" });
      const queue = await readQueue(store, TASK_QUEUE_KEY);
      queue.push({
        text,
        tag: typeof body.tag === "string" && body.tag ? body.tag : "기타",
        ts: Date.now(),
      });
      await store.setJSON(TASK_QUEUE_KEY, queue);
      return json(200, { ok: true, count: queue.length });
    }

    if (action === "dashboard_pull" && method === "GET") {
      const queue = await readQueue(store, TASK_QUEUE_KEY);
      await clearQueue(store, TASK_QUEUE_KEY);
      return json(200, { tasks: queue });
    }

    if (action === "task_saved" && method === "POST") {
      const body = parseBody(event);
      let tasks = [];
      if (Array.isArray(body.tasks)) {
        tasks = body.tasks
          .map((t) => {
            if (typeof t === "string") return { text: t.trim() };
            if (t && typeof t === "object" && typeof t.text === "string") {
              return {
                text: t.text.trim(),
                tag: t.tag || undefined,
                time: t.time || undefined,
              };
            }
            return null;
          })
          .filter((t) => t && t.text);
      }
      if (tasks.length === 0) return json(400, { error: "tasks required" });
      const events = await readQueue(store, EVENT_QUEUE_KEY);
      events.push({
        type: "task_saved",
        tasks,
        time: typeof body.time === "string" ? body.time : "",
        ts: Date.now(),
      });
      await store.setJSON(EVENT_QUEUE_KEY, events);
      return json(200, { ok: true, count: tasks.length });
    }

    if (action === "bot_pull" && method === "GET") {
      const events = await readQueue(store, EVENT_QUEUE_KEY);
      await clearQueue(store, EVENT_QUEUE_KEY);
      return json(200, { events });
    }

    return json(400, { error: "unknown action or method", action, method });
  } catch (e) {
    return json(500, { error: "internal", detail: String(e && e.message || e) });
  }
};
