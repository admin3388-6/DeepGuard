// api/config.js — Vercel API مع دعم استهداف نسخ متعددة
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") return res.status(200).end();

  if (typeof req.body === "string" && req.body.trim()) {
    try { req.body = JSON.parse(req.body); } catch(e) {}
  }

  const SUPA_URL = process.env.SUPABASE_URL || "";
  const SUPA_KEY = process.env.SUPABASE_KEY || "";
  const ADMIN_PASS = process.env.ADMIN_PASSWORD || "admin123";
  const OS_APP_ID = process.env.ONESIGNAL_APP_ID || "";
  const OS_REST_KEY = process.env.ONESIGNAL_REST_KEY || "";
  const TOPAI_KEY = process.env.TOPAI_KEY || "";
  const TOPAI_BASE = (process.env.TOPAI_BASE || "https://top-tools-ai.com/api/v1").replace(/\/$/, "");
  const TOPAI_MODEL = process.env.TOPAI_MODEL || "GLM-5.3-Flash";
  const GROQ_KEY = process.env.GROQ_API_KEY || "";

  async function aiAsk(messages, maxTokens = 700) {
    const tryTopAI = async () => {
      if (!TOPAI_KEY) return "";
      const r = await fetch(TOPAI_BASE + "/chat/completions", {
        method: "POST",
        headers: { "Authorization": `Bearer ${TOPAI_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: TOPAI_MODEL, messages, max_tokens: maxTokens })
      });
      const d = await r.json();
      return ((d.choices && d.choices[0].message.content) || "").trim();
    };
    const tryGroq = async () => {
      if (!GROQ_KEY) return "";
      const models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.8-27b"];
      for (const m of models) {
        try {
          const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
            method: "POST",
            headers: { "Authorization": `Bearer ${GROQ_KEY}`, "Content-Type": "application/json" },
            body: JSON.stringify({ model: m, messages, max_tokens: maxTokens })
          });
          const d = await r.json();
          const txt = ((d.choices && d.choices[0].message.content) || "").trim();
          if (txt) return txt;
        } catch(e) {}
      }
      return "";
    };
    for (const fn of [tryTopAI, tryGroq]) {
      try { const out = await fn(); if (out) return out; } catch (e) {}
    }
    return "";
  }

  async function memGet() {
    if (!SUPA_URL || !SUPA_KEY) return [];
    try {
      const r = await fetch(`${SUPA_URL}/rest/v1/app_config?id=eq.ai_memory&select=config`, {
        headers: { "apikey": SUPA_KEY, "Authorization": `Bearer ${SUPA_KEY}` }
      });
      const rows = await r.json();
      return (rows && rows[0] && rows[0].config && rows[0].config.memories) || [];
    } catch (e) { return []; }
  }
  async function memSet(memories) {
    if (!SUPA_URL || !SUPA_KEY) return false;
    const r = await fetch(`${SUPA_URL}/rest/v1/app_config`, {
      method: "POST",
      headers: { "apikey": SUPA_KEY, "Authorization": `Bearer ${SUPA_KEY}`, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates" },
      body: JSON.stringify({ id: "ai_memory", config: { memories: memories.slice(-200) } })
    });
    return r.ok;
  }
  async function memSearch(q) {
    const ql = (q || "").toLowerCase();
    const all = await memGet();
    return all.filter(m => !ql || (m.key + " " + m.content).toLowerCase().includes(ql)).slice(-15);
  }
  async function fetchDevices() {
    if (!SUPA_URL || !SUPA_KEY) return [];
    const r = await fetch(`${SUPA_URL}/rest/v1/app_devices?select=*&order=last_seen.desc&limit=200`, {
      headers: { "apikey": SUPA_KEY, "Authorization": `Bearer ${SUPA_KEY}` }
    });
    return await r.json();
  }

  const { v, vn, did, os: androidOs, stats } = req.query;

  // 1. تسجيل نشاط الجهاز في Supabase
  if (req.method === "GET" && did && SUPA_URL && SUPA_KEY) {
    fetch(`${SUPA_URL}/rest/v1/app_devices`, {
      method: "POST",
      headers: {
        "apikey": SUPA_KEY,
        "Authorization": `Bearer ${SUPA_KEY}`,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
      },
      body: JSON.stringify({
        device_id: did,
        version_code: parseInt(v) || 1,
        version_name: vn || "1.0",
        android_os: parseInt(androidOs) || 0,
        last_seen: new Date().toISOString()
      })
    }).catch(() => {});
  }

  // 2. إرجاع إحصائيات الأجهزة وتجميع النسخ للوحة التحكم
  if (req.method === "GET" && stats === "1") {
    if (!SUPA_URL || !SUPA_KEY) return res.status(200).json({ ok: false, error: "Supabase غير متصل" });
    try {
      const resp = await fetch(`${SUPA_URL}/rest/v1/app_devices?select=*&order=last_seen.desc&limit=150`, {
        headers: { "apikey": SUPA_KEY, "Authorization": `Bearer ${SUPA_KEY}` }
      });
      const devices = await resp.json();
      return res.status(200).json({ ok: true, devices });
    } catch (e) {
      return res.status(500).json({ ok: false, error: e.message });
    }
  }

  // 2.5 ذاكرة AI المشتركة (قراءة)
  if (req.method === "GET" && req.query.action === "memory") {
    const q = req.query.q || "";
    return res.status(200).json({ ok: true, memories: await memSearch(q) });
  }

  // 3. إرسال الإعدادات لتطبيق الهاتف
  if (req.method === "GET") {
    let cfg = {
      kill_switch: false,
      kill_msg: "التطبيق متوقف مؤقتاً لأعمال الصيانة",
      target_versions: [], // فارغ = كل النسخ، أو مصفوفة بالنسخ المحددة
      min_version: 1,
      update_url: "",
      upd_title: "تحديث جديد",
      upd_msg: "يتوفر إصدار جديد للتطبيق، يرجى التحديث لمتابعة الاستخدام.",
      msg_title: "",
      msg_body: "",
      img_url: "",
      remote_js: ""
    };

    if (SUPA_URL && SUPA_KEY) {
      try {
        const sRes = await fetch(`${SUPA_URL}/rest/v1/app_config?id=eq.global&select=config`, {
          headers: { "apikey": SUPA_KEY, "Authorization": `Bearer ${SUPA_KEY}` }
        });
        const rows = await sRes.json();
        if (rows && rows.length > 0 && rows[0].config) {
          cfg = rows[0].config;
        }
      } catch (e) {}
    }
    return res.status(200).json(cfg);
  }

  // 4. معالجة طلبات لوحة التحكم (POST)
  if (req.method === "POST") {
    const token = (req.headers["authorization"] || "").replace("Bearer ", "").trim();
    if (token !== ADMIN_PASS) {
      return res.status(401).json({ ok: false, error: "كلمة المرور غير صحيحة" });
    }

    const { action } = req.query;

    if (action === "chat") {
      const { message, context } = req.body || {};
      if (!message) return res.status(400).json({ ok: false, error: "اكتب رسالة" });
      const mem = await memSearch(message.slice(0, 60));
      const sys = "أنت مساعد Deep Guard (لوحة تحكم تطبيقات Android) بالعربية. أجب بإيجاز عملي. ذكريات مرتبطة:\n" +
        mem.map(m => `- ${m.key}: ${String(m.content).slice(0, 200)}`).join("\n");
      const answer = await aiAsk([
        { role: "system", content: sys },
        { role: "user", content: ((context || "") + "\n" + message).slice(0, 3000) }
      ]);
      if (!answer) return res.status(502).json({ ok: false, error: "تعذر الوصول لأي نموذج AI" });
      return res.status(200).json({ ok: true, answer, model: TOPAI_MODEL });
    }

    if (action === "agent") {
      const { message } = req.body || {};
      if (!message) return res.status(400).json({ ok: false, error: "اكتب مهمة" });
      const devices = await fetchDevices();
      const versions = {};
      (Array.isArray(devices) ? devices : []).forEach(d => {
        const k = `${d.version_name} (${d.version_code})`;
        versions[k] = (versions[k] || 0) + 1;
      });
      const sys = "أنت وكيل تحليل أجهزة المستخدمين. أجب بالعربية JSON فقط: " +
        '{"tool":"devices"|"versions"|"memory_search"|"memory_save","args":{...}} أو {"final":"الإجابة"}. ' +
        `لديك فورًا: ${devices.length} جهاز. النسخ: ${JSON.stringify(versions)}. ` +
        "للبحث عن نسخة معينة: أداة versions ثم حلل.";
      let history = [
        { role: "system", content: sys },
        { role: "user", content: String(message).slice(0, 1500) }
      ];
      const steps = [];
      for (let i = 0; i < 4; i++) {
        const raw = await aiAsk(history, 600);
        const m = raw.match(/\{[\s\S]*\}/);
        if (!m) return res.status(200).json({ ok: true, answer: raw || "…", steps });
        let act; try { act = JSON.parse(m[0]); } catch (e) { return res.status(200).json({ ok: true, answer: raw, steps }); }
        if (act.final) return res.status(200).json({ ok: true, answer: String(act.final), steps });
        let result = { error: "أداة غير معروفة" };
        if (act.tool === "devices") result = { count: devices.length, sample: devices.slice(0, 5) };
        if (act.tool === "versions") result = { versions };
        if (act.tool === "memory_search") result = { results: await memSearch(act.args && act.args.query || "") };
        if (act.tool === "memory_save") result = { saved: await memSet([...(await memGet()), { key: String(act.args.key || "note").slice(0, 80), content: String(act.args.content || "").slice(0, 2000), at: new Date().toISOString() }]) };
        steps.push({ tool: act.tool });
        history.push({ role: "assistant", content: m[0] });
        history.push({ role: "user", content: "نتيجة الأداة:\n" + JSON.stringify(result).slice(0, 2500) + "\nأكمل JSON فقط." });
      }
      return res.status(200).json({ ok: true, answer: "توقفت بعد أقصى خطوات.", steps });
    }

    if (action === "memory") {
      const { key, content, del } = req.body || {};
      if (del) { await memSet((await memGet()).filter(x => x.key !== del)); return res.status(200).json({ ok: true }); }
      if (!key) return res.status(400).json({ ok: false, error: "أدخل مفتاح" });
      await memSet([...(await memGet()), { key: String(key).slice(0, 80), content: String(content || "").slice(0, 2000), at: new Date().toISOString() }]);
      return res.status(200).json({ ok: true });
    }

    if (action === "push") {
      if (!OS_APP_ID || !OS_REST_KEY) {
        return res.status(400).json({ ok: false, error: "يرجى ضبط متغيرات OneSignal" });
      }
      try {
        const pushBody = req.body;
        const osRes = await fetch("https://onesignal.com/api/v1/notifications", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Basic ${OS_REST_KEY}`
          },
          body: JSON.stringify({
            app_id: OS_APP_ID,
            included_segments: ["Total Subscriptions"],
            headings: { en: pushBody.title, ar: pushBody.title },
            contents: { en: pushBody.message, ar: pushBody.message },
            url: pushBody.url || undefined,
            big_picture: pushBody.img_url || undefined,
            small_icon: "ic_stat_onesignal_default"
          })
        });
        const osData = await osRes.json();
        return res.status(200).json({ ok: true, recipients: osData.recipients || 0 });
      } catch (err) {
        return res.status(500).json({ ok: false, error: err.message });
      }
    }

    try {
      const data = req.body;
      if (SUPA_URL && SUPA_KEY) {
        await fetch(`${SUPA_URL}/rest/v1/app_config`, {
          method: "POST",
          headers: {
            "apikey": SUPA_KEY,
            "Authorization": `Bearer ${SUPA_KEY}`,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
          },
          body: JSON.stringify({ id: "global", config: data })
        });
      }
      return res.status(200).json({ ok: true, msg: "تم حفظ الإعدادات" });
    } catch (err) {
      return res.status(500).json({ ok: false, error: err.message });
    }
  }

  return res.status(405).end();
}
