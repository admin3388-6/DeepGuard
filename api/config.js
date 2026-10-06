// api/config.js — Vercel API مع دعم استهداف نسخ متعددة
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") return res.status(200).end();

  const SUPA_URL = process.env.SUPABASE_URL || "";
  const SUPA_KEY = process.env.SUPABASE_KEY || "";
  const ADMIN_PASS = process.env.ADMIN_PASSWORD || "admin123";
  const OS_APP_ID = process.env.ONESIGNAL_APP_ID || "";
  const OS_REST_KEY = process.env.ONESIGNAL_REST_KEY || "";

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
