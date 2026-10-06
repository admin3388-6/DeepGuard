// api/config.js — Vercel Serverless with Supabase Device Tracking
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") return res.status(200).end();

  const SUPA_URL = process.env.SUPABASE_URL || "";
  const SUPA_KEY = process.env.SUPABASE_KEY || "";
  const ADMIN_PASS = process.env.ADMIN_PASSWORD || "admin123";

  // 1. تسجيل نشاط الجهاز في Supabase عند الاتصال
  const { v, vn, did, os: androidOs } = req.query;
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

  // 2. إرسال الإعدادات لتطبيق أندرويد
  if (req.method === "GET") {
    let cfg = {
      kill_switch: false,
      kill_msg: "التطبيق متوقف للصيانة",
      target_v: 0, // 0 يعني كل النسخ، أو ضع رقم إصدار معين (مثل 1)
      min_version: 1,
      update_url: "",
      upd_title: "تحديث جديد متوفر",
      upd_msg: "يرجى تنزيل الإصدار الأخير.",
      msg_title: "",
      msg_body: "",
      img_url: "", // رابط صورة للإعلان أو القفل
      remote_js: ""
    };
    if (process.env.CONFIG_DATA) {
      try { cfg = JSON.parse(process.env.CONFIG_DATA); } catch (e) {}
    }
    return res.status(200).json(cfg);
  }

  // 3. حفظ الإعدادات من لوحة التحكم
  if (req.method === "POST") {
    const token = (req.headers["authorization"] || "").replace("Bearer ", "").trim();
    if (token !== ADMIN_PASS) {
      return res.status(401).json({ ok: false, error: "كلمة المرور غير صحيحة" });
    }
    return res.status(200).json({ ok: true, msg: "تم الحفظ" });
  }

  return res.status(405).end();
}
