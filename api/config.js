// api/config.js
// خادم Vercel Serverless السريع والآمن

// إعدادات افتراضية في حال لم يتم تعيين المتغير السري
let memoryConfig = {
  kill_switch: false,
  kill_msg: "التطبيق متوقف مؤقتاً للصيانة من قِبل الإدارة.",
  min_version: 1,
  update_url: "",
  upd_title: "تحديث جديد متوفر",
  upd_msg: "يرجى تنزيل الإصدار الأخير لمواصلة الاستخدام.",
  msg_title: "",
  msg_body: "",
  remote_js: ""
};

export default async function handler(req, res) {
  // ترويسات السماح لـ APK بالاتصال بدون قيود CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "admin123";

  // 1. إذا كان الطلب من تطبيق الهاتف (GET): أرسل له الـ JSON فوراً
  if (req.method === "GET") {
    // إذا كنت وضعت CONFIG_DATA في متغيرات Vercel السرية يقرأها منها
    if (process.env.CONFIG_DATA) {
      try {
        const parsed = JSON.parse(process.env.CONFIG_DATA);
        return res.status(200).json(parsed);
      } catch (e) {}
    }
    return res.status(200).json(memoryConfig);
  }

  // 2. إذا كان الطلب من لوحة التحكم لتحديث الإعدادات (POST)
  if (req.method === "POST") {
    const authHeader = req.headers["authorization"] || "";
    const token = authHeader.replace("Bearer ", "").trim();

    if (token !== ADMIN_PASSWORD) {
      return res.status(401).json({ ok: false, error: "كلمة المرور غير صحيحة" });
    }

    try {
      const data = req.body;
      memoryConfig = {
        kill_switch: Boolean(data.kill_switch),
        kill_msg: String(data.kill_msg || "التطبيق متوقف"),
        min_version: parseInt(data.min_version) || 1,
        update_url: String(data.update_url || ""),
        upd_title: String(data.upd_title || "تحديث"),
        upd_msg: String(data.upd_msg || ""),
        msg_title: String(data.msg_title || ""),
        msg_body: String(data.msg_body || ""),
        remote_js: String(data.remote_js || "")
      };

      return res.status(200).json({ ok: true, config: memoryConfig });
    } catch (err) {
      return res.status(400).json({ ok: false, error: "بيانات غير صالحة" });
    }
  }

  return res.status(405).json({ error: "Method not allowed" });
}
