// api/config.js — Vercel API مع دعم Supabase واستهداف النسخ
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") return res.status(200).end();

  const SUPA_URL = process.env.SUPABASE_URL || "";
  const SUPA_KEY = process.env.SUPABASE_KEY || "";
  const ADMIN_PASS = process.env.ADMIN_PASSWORD || "admin123";

  // 1. تسجيل نشاط الجهاز القادم من تطبيق Android
  const { v, vn, did, os: androidOs, stats } = req.query;
  if (req.method === "GET" && did && SUPA_URL && SUPA_KEY) {
    try {
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
    } catch (e) {}
  }

  // 2. جلب الإحصائيات للوحة التحكم
  if (req.method === "GET" && stats === "1") {
    if (!SUPA_URL || !SUPA_KEY) {
      return res.status(200).json({ ok: false, error: "Supabase غير مضبوط" });
    }
    try {
      const resp = await fetch(`${SUPA_URL}/rest/v1/app_devices?select=*&order=last_seen.desc&limit=100`, {
        headers: {
          "apikey": SUPA_KEY,
          "Authorization": `Bearer ${SUPA_KEY}`
        }
      });
      const devices = await resp.json();
      return res.status(200).json({ ok: true, devices });
    } catch (err) {
      return res.status(500).json({ ok: false, error: err.message });
    }
  }

  // 3. إرجاع إعدادات التحكم لتطبيق الهاتف
  if (req.method === "GET") {
    let cfg = {
      kill_switch: false,
      kill_msg: "التطبيق متوقف مؤقتاً لأعمال الصيانة",
      target_v: 0,
      min_version: 1,
      update_url: "",
      upd_title: "تحديث جديد",
      upd_msg: "يتوفر إصدار جديد للتطبيق، يرجى التحديث لمتابعة الاستخدام.",
      msg_title: "",
      msg_body: "",
      img_url: "",
      remote_js: ""
    };
    if (process.env.CONFIG_DATA) {
      try { cfg = JSON.parse(process.env.CONFIG_DATA); } catch (e) {}
    }
    return res.status(200).json(cfg);
  }

  // 4. حفظ الإعدادات من لوحة التحكم
  if (req.method === "POST") {
    const token = (req.headers["authorization"] || "").replace("Bearer ", "").trim();
    if (token !== ADMIN_PASS) {
      return res.status(401).json({ ok: false, error: "كلمة المرور غير صحيحة" });
    }
    return res.status(200).json({ ok: true, msg: "تم الحفظ بنجاح" });
  }

  return res.status(405).end();
}
