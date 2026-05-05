// Netlify Function: AI 태스크 정리
//
// POST /.netlify/functions/claude
//   body: { text: string }              — raw telegram paste
//   resp: { tasks: [{text,tag,time?}] } — structured tasks for the dashboard
//
// Calls Anthropic Messages API via Node's https module (no fetch).

const https = require("https");

const MODEL = "claude-sonnet-4-20250514";
const ALLOWED_TAGS = ["호니아", "술펀", "운명책", "자기", "기타"];

const SYSTEM = [
  "당신은 이수진의 일정/메모를 구조화하는 보조 모델입니다.",
  "사용자가 텔레그램에 적어둔 자유 텍스트(메모, 대화, 메모: 태그 형식 섞임)를",
  "오늘 처리할 태스크 목록으로 추출합니다.",
  "",
  "출력은 반드시 아래 JSON 스키마만 내보낼 것 (코드펜스 금지, 부가 설명 금지):",
  '{"tasks":[{"text":"<짧은 한 줄, 한국어 명사구>","tag":"<호니아|술펀|운명책|자기|기타>","time":"<HH:MM 또는 빈 문자열>"}]}',
  "",
  "규칙:",
  "- 단순 안부/잡담은 태스크가 아니므로 제외.",
  "- '메모: ... #호니아' 같이 명시된 태그가 있으면 그대로 매핑(honia→호니아, sulfun→술펀, book→운명책).",
  "- 명시 시간(예: 오후 3시, 15:00)이 있으면 24h HH:MM, 없으면 빈 문자열.",
  "- text 는 30자 이내 한국어 명사구로 압축. 마침표/이모지 금지.",
  "- 도메인 추정: HOrN/혼김/IR/투자자/미국→호니아, 라운지/한정혜/SOP/거래처→술펀, 원고/코칭/패키지/서브스택→운명책, 요가/체중/수면/산책→자기, 그 외→기타.",
  "- 같은 의도 중복 항목은 1개로 합칠 것.",
  "- 태스크가 없다고 판단되면 {\"tasks\":[]} 반환.",
].join("\n");

function jsonResp(statusCode, obj) {
  return {
    statusCode,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(obj),
  };
}

function callAnthropic(apiKey, payload) {
  const body = Buffer.from(JSON.stringify(payload), "utf-8");
  const opts = {
    method: "POST",
    hostname: "api.anthropic.com",
    path: "/v1/messages",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "content-length": body.length,
    },
  };
  return new Promise((resolve, reject) => {
    const req = https.request(opts, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf-8");
        try {
          resolve({ status: res.statusCode || 0, json: JSON.parse(raw) });
        } catch (_) {
          resolve({ status: res.statusCode || 0, json: { raw } });
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(25_000, () => req.destroy(new Error("anthropic timeout")));
    req.write(body);
    req.end();
  });
}

function extractFirstJSONObject(s) {
  if (!s) return null;
  const start = s.indexOf("{");
  if (start < 0) return null;
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < s.length; i++) {
    const c = s[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') inStr = true;
    else if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) {
        try { return JSON.parse(s.slice(start, i + 1)); } catch { return null; }
      }
    }
  }
  return null;
}

function normalizeTasks(arr) {
  if (!Array.isArray(arr)) return [];
  const tagAliases = {
    honia: "호니아", horn: "호니아", "호니아": "호니아",
    sulfun: "술펀", "술펀": "술펀",
    book: "운명책", "운명책": "운명책",
    self: "자기", "자기": "자기",
    "기타": "기타", other: "기타", etc: "기타",
  };
  const out = [];
  for (const item of arr) {
    if (!item || typeof item !== "object") continue;
    const text = String(item.text || "").trim();
    if (!text) continue;
    const tagRaw = String(item.tag || "").trim().toLowerCase();
    const tag = tagAliases[tagRaw] || (ALLOWED_TAGS.includes(item.tag) ? item.tag : "기타");
    let time = String(item.time || "").trim();
    if (time && !/^\d{2}:\d{2}$/.test(time)) time = "";
    out.push({ text: text.slice(0, 60), tag, time });
  }
  return out;
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return jsonResp(405, { error: "POST only" });
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return jsonResp(500, { error: "ANTHROPIC_API_KEY not set" });

  let body = {};
  try {
    const raw = event.isBase64Encoded
      ? Buffer.from(event.body || "", "base64").toString("utf-8")
      : (event.body || "");
    body = raw ? JSON.parse(raw) : {};
  } catch (_) {
    return jsonResp(400, { error: "invalid JSON body" });
  }
  const text = String(body.text || "").trim();
  if (!text) return jsonResp(400, { error: "text required" });
  if (text.length > 8000) return jsonResp(413, { error: "text too long" });

  let resp;
  try {
    resp = await callAnthropic(apiKey, {
      model: MODEL,
      max_tokens: 1024,
      system: SYSTEM,
      messages: [{ role: "user", content: text }],
    });
  } catch (e) {
    return jsonResp(502, { error: "upstream", detail: String(e && e.message || e) });
  }
  if (resp.status < 200 || resp.status >= 300) {
    return jsonResp(resp.status || 502, {
      error: "anthropic error",
      detail: resp.json && resp.json.error ? resp.json.error : resp.json,
    });
  }

  const content = resp.json && Array.isArray(resp.json.content) ? resp.json.content : [];
  const txt = content.map((b) => (b && b.type === "text" ? b.text : "")).join("");
  const parsed = extractFirstJSONObject(txt);
  const tasks = normalizeTasks(parsed && parsed.tasks);
  return jsonResp(200, { tasks });
};
