// Metis ↔ Better Sujin Bridge
// Deploy this file to the dashboard repo (sujinos.netlify.app) under
// netlify/functions/tg-bridge.js. Uses Netlify Blobs as the queue.
//
// Endpoints (all require X-Bridge-Token header == BRIDGE_TOKEN env var):
//   POST /api/tg-bridge?action=push_task        body: {text, tag}    — bot → queue
//   GET  /api/tg-bridge?action=dashboard_pull                         — dashboard reads + clears
//   POST /api/tg-bridge?action=task_saved       body: {text, time?}  — dashboard → queue
//   GET  /api/tg-bridge?action=bot_pull                               — bot polls + clears

import { getStore } from "@netlify/blobs";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });

export default async (req) => {
  const url = new URL(req.url);
  const action = url.searchParams.get("action");
  const expected = Netlify.env.get("BRIDGE_TOKEN");

  if (!expected) return json({ error: "BRIDGE_TOKEN not set" }, 500);
  if (req.headers.get("x-bridge-token") !== expected) {
    return json({ error: "unauthorized" }, 401);
  }

  const store = getStore("metis-bridge");

  if (action === "push_task" && req.method === "POST") {
    const body = await req.json().catch(() => ({}));
    if (!body.text) return json({ error: "text required" }, 400);
    const inbox = (await store.get("dashboard_inbox", { type: "json" })) || [];
    inbox.push({
      text: body.text,
      tag: body.tag || "기타",
      ts: Date.now(),
    });
    await store.setJSON("dashboard_inbox", inbox);
    return json({ ok: true, count: inbox.length });
  }

  if (action === "dashboard_pull" && req.method === "GET") {
    const inbox = (await store.get("dashboard_inbox", { type: "json" })) || [];
    await store.setJSON("dashboard_inbox", []);
    return json({ tasks: inbox });
  }

  if (action === "task_saved" && req.method === "POST") {
    const body = await req.json().catch(() => ({}));
    if (!body.text) return json({ error: "text required" }, 400);
    const events = (await store.get("bot_inbox", { type: "json" })) || [];
    events.push({
      type: "task_saved",
      text: body.text,
      time: body.time || "",
      ts: Date.now(),
    });
    await store.setJSON("bot_inbox", events);
    return json({ ok: true });
  }

  if (action === "tg_send" && req.method === "POST") {
    const body = await req.json().catch(() => ({}));
    if (!body.text) return json({ error: "text required" }, 400);
    const events = (await store.get("bot_inbox", { type: "json" })) || [];
    events.push({ type: "tg_send", text: body.text, ts: Date.now() });
    await store.setJSON("bot_inbox", events);
    return json({ ok: true });
  }

  if (action === "bot_pull" && req.method === "GET") {
    const events = (await store.get("bot_inbox", { type: "json" })) || [];
    await store.setJSON("bot_inbox", []);
    return json({ events });
  }

  return json({ error: "unknown action", action }, 400);
};

export const config = { path: "/api/tg-bridge" };
