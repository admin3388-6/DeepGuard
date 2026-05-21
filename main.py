import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
import re
import asyncio
import aiohttp
from collections import defaultdict, deque
from datetime import timedelta, datetime
import time
from dotenv import load_dotenv
import urllib.parse
import hashlib
from flask import Flask
from threading import Thread
import logging

# ==========================================
# إعدادات التسجيل (لتشخيص الأخطاء)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("DeepGuard")

# ==========================================
# Keep Alive Server (لـ Render & Railway)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "DeepGuard v2.0 is ACTIVE!"

@app.route('/health')
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    t = Thread(target=run_server, daemon=True)
    t.start()

# ==========================================
# تحميل الإعدادات مع التحقق
# ==========================================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
SAFE_BROWSING_API_KEY = os.getenv('SAFE_BROWSING_API_KEY', '')

if not TOKEN:
    logger.error("❌ DISCORD_TOKEN غير موجود في المتغيرات البيئية!")
    exit(1)

# ==========================================
# الإعدادات الأساسية
# ==========================================
CONTROL_CHANNEL_ID = 1506420018890543114
LOG_CHANNEL_ID = 1506420345387876402

IGNORED_CHANNELS = {
    1504557542825529374,
    1504556508103577743,
    1497648145666932826,
    1497621523639570524,
    LOG_CHANNEL_ID  # نتجاهل الثريد نفسه من الفلاتر
}

SUPREME_ROLES = {1505681669418647594, 1497618182763053096}
OWNER_ROLES = {1497646073060003982}
ADMIN_ROLES = {1504544220030173265, 1504575260563865681}

# ==========================================
# أنظمة الحماية والكاش
# ==========================================
SHORTENER_DOMAINS = {
    "bit.ly", "goo.gl", "tinyurl.com", "t.co", "cutt.ly", "is.gd", "buff.ly",
    "short.link", "ow.ly", "rebrand.ly", "rb.gy", "clck.ru", "shorturl.at",
    "tr.im", "cli.gs", "u.to", "v.gd", "short.io", "bl.ink", "t.ly"
}

URL_REGEX = re.compile(r'(https?://[^\s<<>`"|\[\]\{\}]+)', re.IGNORECASE)

class TTLCache:
    def __init__(self, ttl=1800):
        self._data = {}
        self._ttl = ttl
    def get(self, key):
        if key not in self._data:
            return None
        val, ts = self._data[key]
        if time.time() - ts > self._ttl:
            del self._data[key]
            return None
        return val
    def set(self, key, val):
        self._data[key] = (val, time.time())
    def cleanup(self):
        now = time.time()
        expired = [k for k, (_, ts) in self._data.items() if now - ts > self._ttl]
        for k in expired:
            del self._data[k]

url_cache = TTLCache(ttl=1800)
user_msg_cache = defaultdict(lambda: deque(maxlen=50))
user_warnings = defaultdict(int)
user_spam_score = defaultdict(float)
punishment_history = defaultdict(list)
cmd_usage = defaultdict(lambda: deque(maxlen=10))

# ==========================================
# دوال مساعدة
# ==========================================
def get_user_level(member: discord.Member) -> int:
    if member.guild.owner_id == member.id:
        return 3
    rids = {r.id for r in member.roles}
    if rids & SUPREME_ROLES:
        return 3
    if rids & OWNER_ROLES:
        return 2
    if rids & ADMIN_ROLES:
        return 1
    return 0

async def get_log_target(guild: discord.Guild):
    """البحث عن قناة/ثريد اللوقز بشكل آمن"""
    try:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            return ch
        # محاولة جلبه عبر API إذا لم يكن في الكاش
        ch = await bot.fetch_channel(LOG_CHANNEL_ID)
        return ch
    except Exception as e:
        logger.error(f"[LOG] فشل العثور على الثريد: {e}")
        return None

async def send_log(guild: discord.Guild, title: str, desc: str, color: discord.Color,
                   member: discord.Member = None, msg_link: str = None,
                   channel: discord.abc.GuildChannel = None):
    try:
        log_ch = await get_log_target(guild)
        if not log_ch:
            logger.warning(f"[LOG SKIP] لم يتم العثور على قناة اللوقز {LOG_CHANNEL_ID}")
            return

        embed = discord.Embed(title=title, description=desc, color=color,
                              timestamp=discord.utils.utcnow())
        if member:
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(name="المستخدم", value=f"{member.mention} | `{member.id}`", inline=False)
        if msg_link:
            embed.add_field(name="الرسالة", value=f"[اضغط هنا]({msg_link})", inline=False)
        if channel:
            embed.add_field(name="القناة", value=channel.mention, inline=False)

        await log_ch.send(embed=embed)
    except Exception as e:
        logger.error(f"[LOG ERROR] {e}")

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', text)
    trans = str.maketrans({
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ء': '', 'ئ': 'ي', 'ؤ': 'و',
        'ة': 'ه', 'ى': 'ي', 'ﻷ': 'لا', 'ﻹ': 'لا', 'ﻻ': 'لا',
        '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '8': 'b', '9': 'g',
        '@': 'a', '$': 's', '!': 'i', '£': 'l', '€': 'e', '&': 'and', '#': 'h',
        '٥': 's', '٤': 'a', '١': 'i', '٠': 'o', '٣': 'e'
    })
    return text.translate(trans).lower()

async def check_url_safety(url: str, session: aiohttp.ClientSession) -> tuple[bool, str]:
    key = hashlib.md5(url.lower().encode()).hexdigest()
    cached = url_cache.get(key)
    if cached is not None:
        return cached

    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
    except:
        return (True, "رابط غير صالح")

    if any(s in domain for s in SHORTENER_DOMAINS):
        result = (True, "رابط مختصر - محظور افتراضياً")
        url_cache.set(key, result)
        return result

    if "discord.gg" in url.lower() or "discord.com/invite" in url.lower():
        result = (False, "دعوة ديسكورد - يتطلب مراجعة يدوية")
        url_cache.set(key, result)
        return result

    if SAFE_BROWSING_API_KEY and session:
        try:
            api_url = f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={SAFE_BROWSING_API_KEY}"
            payload = {
                "client": {"clientId": "deepguard", "clientVersion": "2.0"},
                "threatInfo": {
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                   "POTENTIALLY_HARMFUL_APPLICATION"],
                    "platformTypes": ["ANY_PLATFORM"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [{"url": url}]
                }
            }
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("matches"):
                        result = (True, "رابط ضار (Google Safe Browsing)")
                        url_cache.set(key, result)
                        return result
                else:
                    logger.warning(f"[API] Safe Browsing status: {resp.status}")
        except Exception as e:
            logger.warning(f"[API] Safe Browsing error: {e}")

    result = (False, "آمن (لم يتم العثور على تهديدات)")
    url_cache.set(key, result)
    return result

async def auto_punish(member: discord.Member, reason: str, severity: str = "low",
                      channel: discord.TextChannel = None, msg: discord.Message = None):
    try:
        now = datetime.utcnow()
        msg_link = msg.jump_url if msg else None

        if severity == "critical":
            duration = timedelta(hours=6)
            punish_reason = f"تخريب متعمد مؤكد: {reason}"
            user_warnings[member.id] = 0
            color = discord.Color.dark_red()
        elif severity == "high":
            duration = timedelta(minutes=10)
            punish_reason = f"مخالفة خطيرة: {reason}"
            user_warnings[member.id] += 1
            color = discord.Color.red()
        elif severity == "medium":
            duration = timedelta(minutes=10)
            punish_reason = f"مخالفة متوسطة: {reason}"
            user_warnings[member.id] += 1
            color = discord.Color.orange()
        else:
            user_warnings[member.id] += 1
            warns = user_warnings[member.id]
            if warns < 3:
                warn_text = f"⚠️ **تحذير DeepGuard** {member.mention}\n**السبب:** {reason}\n**التحذير:** {warns}/3"
                if channel:
                    try:
                        await channel.send(warn_text, delete_after=20)
                    except:
                        pass
                try:
                    await member.send(f"⚠️ **تحذير إداري**\nالسبب: {reason}\nالتحذير رقم {warns}/3\nيرجى الالتزام بقوانين السيرفر.", delete_after=60)
                except:
                    pass
                await send_log(member.guild, "تحذير تلقائي", reason,
                              discord.Color.yellow(), member, msg_link, channel)
                return
            else:
                duration = timedelta(hours=1)
                punish_reason = f"تجاوز التحذيرات (3/3): {reason}"
                user_warnings[member.id] = 0
                color = discord.Color.orange()

        await member.timeout(duration, reason=punish_reason)
        punishment_history[member.id].append({
            "time": now.isoformat(),
            "reason": punish_reason,
            "duration": str(duration),
            "severity": severity
        })

        if channel:
            try:
                await channel.send(
                    f"🚫 **{member.mention} تايم أوت**\n**السبب:** {punish_reason}\n**المدة:** {duration}",
                    delete_after=30
                )
            except:
                pass
        try:
            await member.send(f"🚫 **تم معاقبتك**\nالسبب: {punish_reason}\nالمدة: {duration}\nيرجى الالتزام بقوانين السيرفر.")
        except:
            pass

        await send_log(member.guild, f"عقوبة: {severity.upper()}", punish_reason,
                      color, member, msg_link, channel)

    except Exception as e:
        logger.error(f"[PUNISH ERROR] {e}")
        await send_log(member.guild, "فشل العقوبة", str(e), discord.Color.red(), member)

def check_rate_limit(user_id: int, cooldown: int = 5) -> bool:
    now = time.time()
    usage = cmd_usage[user_id]
    while usage and now - usage[0] > 60:
        usage.popleft()
    recent = [t for t in usage if now - t < cooldown]
    if len(recent) >= 3:
        return False
    usage.append(now)
    return True

# ==========================================
# البوت الرئيسي
# ==========================================
class DeepGuard(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.badwords_patterns = []
        self.load_badwords()
        self.http_session = None

    async def setup_hook(self):
        try:
            self.http_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(
                    limit=15,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                    family=2  # IPv4 فقط
                ),
                timeout=aiohttp.ClientTimeout(total=10)
            )
            self.cache_cleanup.start()
            logger.info("[SETUP] تم تهيئة الجلسة والمهام بنجاح.")
        except Exception as e:
            logger.error(f"[SETUP ERROR] {e}")

    @tasks.loop(minutes=5)
    async def cache_cleanup(self):
        try:
            url_cache.cleanup()
            now = time.time()
            expired_users = []
            for uid in list(user_msg_cache.keys()):
                cache = user_msg_cache[uid]
                while cache and now - cache[0] > 60:
                    cache.popleft()
                if not cache:
                    expired_users.append(uid)
            for uid in expired_users:
                del user_msg_cache[uid]
        except Exception as e:
            logger.error(f"[CLEANUP ERROR] {e}")

    def load_badwords(self):
        try:
            with open('badwords.json', 'r', encoding='utf-8') as f:
                words = json.load(f)
            self.badwords_patterns = []
            for word in words:
                if not word or len(word) < 2:
                    continue
                chars = [re.escape(c) for c in word]
                pattern = r'[\s\W_]*'.join(chars)
                self.badwords_patterns.append(re.compile(pattern, re.IGNORECASE))
            logger.info(f"[DeepGuard] {len(self.badwords_patterns)} كلمة محملة.")
        except FileNotFoundError:
            with open('badwords.json', 'w', encoding='utf-8') as f:
                json.dump([], f)
            logger.info("[DeepGuard] تم إنشاء badwords.json فارغ.")
        except Exception as e:
            logger.error(f"[BADWORDS ERROR] {e}")

bot = DeepGuard()

# ==========================================
# الأحداث
# ==========================================
@bot.event
async def on_ready():
    try:
        logger.info(f"[READY] Logged in as {bot.user} (ID: {bot.user.id})")
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="السيرفر بذكاء | /مساعدة"))
    except Exception as e:
        logger.error(f"[READY ERROR] {e}")

@bot.event
async def on_message(message: discord.Message):
    try:
        if message.author.bot:
            return

        # حماية ثريد اللوقز: حذف فوري + إشعار
        if message.channel.id == LOG_CHANNEL_ID:
            try:
                await message.delete()
                await message.author.send("🚫 **ثريد السجلات للقراءة فقط.** لا يمكنك التحدث هنا.", delete_after=15)
            except:
                pass
            return

        if message.channel.id in IGNORED_CHANNELS:
            return

        if get_user_level(message.author) > 0:
            await bot.process_commands(message)
            return

        content = message.content
        now = time.time()
        channel = message.channel
        author = message.author

        # 1. كشف السبام
        cache = user_msg_cache[author.id]
        cache.append(now)

        recent_10s = [t for t in cache if now - t <= 10]
        if len(recent_10s) >= 4:
            await message.delete()
            user_spam_score[author.id] += 2
            if user_spam_score[author.id] >= 5:
                await auto_punish(author, "سبام مزعج ومتكرر في عدة قنوات", "medium", channel, message)
                user_spam_score[author.id] = 0
            else:
                await auto_punish(author, "إرسال رسائل سريعة متكررة", "medium", channel, message)
            return

        # 2. فلترة الروابط الذكية
        urls = URL_REGEX.findall(content)
        if urls:
            for url in urls:
                is_bad, reason = await check_url_safety(url, bot.http_session)
                if is_bad:
                    await message.delete()
                    await auto_punish(author, f"رابط مشبوه/خبيث: {reason}", "high", channel, message)
                    return

        # 3. فلترة الكلمات السيئة الذكية
        normalized = normalize_text(content)
        for pattern in bot.badwords_patterns:
            if pattern.search(content) or pattern.search(normalized):
                await message.delete()
                history = punishment_history.get(author.id, [])
                recent_violations = [h for h in history
                                   if datetime.fromisoformat(h["time"]) > datetime.utcnow() - timedelta(hours=1)]
                if len(recent_violations) >= 2:
                    await auto_punish(author, "تخريب متعمد - شتم متكرر", "critical", channel, message)
                else:
                    await auto_punish(author, "استخدام ألفاظ نابية/مشفرة", "medium", channel, message)
                return

        # 4. كشف السبام المتراكم (تخريب متعمد)
        if len(cache) >= 8:
            recent_60s = [t for t in cache if now - t <= 60]
            if len(recent_60s) >= 8:
                user_spam_score[author.id] += 1
                if user_spam_score[author.id] >= 3:
                    await message.delete()
                    await auto_punish(author, "تخريب متعمد - سبام مكثف", "critical", channel, message)
                    user_spam_score[author.id] = 0

        await bot.process_commands(message)

    except Exception as e:
        logger.error(f"[on_message ERROR] {e}")

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    try:
        if after.author.bot or after.channel.id in IGNORED_CHANNELS:
            return
        if get_user_level(after.author) > 0:
            return

        urls = URL_REGEX.findall(after.content)
        if urls:
            for url in urls:
                is_bad, reason = await check_url_safety(url, bot.http_session)
                if is_bad:
                    await after.delete()
                    await auto_punish(after.author, f"رابط خبيث (تعديل): {reason}", "high", after.channel, after)
                    return

        normalized = normalize_text(after.content)
        for pattern in bot.badwords_patterns:
            if pattern.search(after.content) or pattern.search(normalized):
                await after.delete()
                await auto_punish(after.author, "تعديل رسالة لإضافة محتوى ممنوع", "medium", after.channel, after)
                return
    except Exception as e:
        logger.error(f"[on_message_edit ERROR] {e}")

# ==========================================
# الأوامر
# ==========================================
@bot.tree.command(name="مساعدة", description="عرض الأوامر المتاحة")
async def help_cmd(interaction: discord.Interaction):
    if not check_rate_limit(interaction.user.id, 10):
        return await interaction.response.send_message("⏳ بطّل شوي!", ephemeral=True)
    embed = discord.Embed(title="🛡️ DeepGuard v2.0 - دليل الأوامر", color=discord.Color.blue())
    embed.add_field(name="📝 إدارية (Admin+)",
                   value="`/تنبيه` - تحذير عضو\n`/تيم_أوت` - تايم أوت\n`/رسالة` - إرسال رسالة باسم البوت",
                   inline=False)
    embed.add_field(name="🔒 عليا (Owner+)",
                   value="`/مسح` - مسح رسائل\n`/حظر` - حظر عضو\n`/إزالة_عقوبة` - إزالة عقوبة\n`/إضافة_عقوبة` - عقوبة يدوية",
                   inline=False)
    embed.add_field(name="👑 Supreme",
                   value="`/ضبط_القائمة` - إضافة كلمة ممنوعة للفلتر",
                   inline=False)
    embed.add_field(name="ℹ️ ملاحظات",
                   value="• جميع الأوامر محمية بـ Rate Limit\n• العقوبات تلقائية وذكية\n• الروابط تُفحص عبر API",
                   inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="تنبيه", description="إرسال تحذير رسمي لعضو")
@app_commands.describe(member="العضو المخالف", reason="سبب التحذير")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not check_rate_limit(interaction.user.id):
        return await interaction.response.send_message("⏳ كثرة استخدام الأوامر! انتظر قليلاً.", ephemeral=True)
    if get_user_level(interaction.user) < 1:
        return await interaction.response.send_message("❌ لا تملك الصلاحية لاستخدام هذا الأمر.", ephemeral=True)
    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك تحذير شخص برتبة مساوية أو أعلى منك.", ephemeral=True)

    await auto_punish(member, f"تحذير إداري: {reason}", "low", interaction.channel)
    await interaction.response.send_message(f"✅ تم توجيه تحذير إلى {member.mention} بنجاح.", ephemeral=True)

@bot.tree.command(name="تيم_أوت", description="إعطاء العضو timeout")
@app_commands.describe(member="العضو", minutes="عدد الدقائق", reason="السبب")
async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "بدون سبب"):
    if not check_rate_limit(interaction.user.id):
        return await interaction.response.send_message("⏳ بطّل شوي!", ephemeral=True)
    if get_user_level(interaction.user) < 1:
        return await interaction.response.send_message("❌ لا تملك الصلاحية.", ephemeral=True)
    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك معاقبة مسؤول.", ephemeral=True)
    if minutes < 1 or minutes > 40320:
        return await interaction.response.send_message("❌ الحد المسموح: 1 إلى 40320 دقيقة.", ephemeral=True)

    try:
        dur = timedelta(minutes=minutes)
        await member.timeout(dur, reason=reason)
        await send_log(interaction.guild, "إجراء إداري: تيم أوت",
                      f"بواسطة: {interaction.user.mention}\nالسبب: {reason}\nالمدة: {minutes} دقيقة",
                      discord.Color.orange(), member)
        await interaction.response.send_message(f"✅ تم إعطاء تيم أوت لـ {member.mention} لمدة {minutes} دقيقة.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ البوت لا يملك صلاحية كافية (تأكد من ترتيب رتبة البوت).", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {str(e)}", ephemeral=True)

@bot.tree.command(name="مسح", description="حذف عدد من الرسائل (للرتب العليا فقط)")
@app_commands.describe(amount="عدد الرسائل (1-100)")
async def purge(interaction: discord.Interaction, amount: int):
    if not check_rate_limit(interaction.user.id, 10):
        return await interaction.response.send_message("⏳ انتظر بين الاستخدامات.", ephemeral=True)
    if get_user_level(interaction.user) < 2:
        return await interaction.response.send_message("❌ هذا الأمر مخصص للرتب العليا فقط.", ephemeral=True)
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ الحد المسموح: 1 إلى 100 رسالة.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await send_log(interaction.guild, "إجراء إداري: مسح رسائل",
                  f"تم مسح {len(deleted)} رسالة في {interaction.channel.mention}\nبواسطة: {interaction.user.mention}",
                  discord.Color.light_grey(), channel=interaction.channel)
    await interaction.followup.send(f"✅ تم مسح {len(deleted)} رسائل بنجاح.")

@bot.tree.command(name="حظر", description="حظر العضو من السيرفر (للرتب العليا فقط)")
@app_commands.describe(member="العضو", reason="السبب")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    if not check_rate_limit(interaction.user.id, 10):
        return await interaction.response.send_message("⏳ انتظر قليلاً.", ephemeral=True)
    if get_user_level(interaction.user) < 2:
        return await interaction.response.send_message("❌ هذا الأمر مخصص للرتب العليا فقط.", ephemeral=True)
    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك حظر شخص برتبة مساوية أو أعلى منك.", ephemeral=True)

    try:
        await member.ban(reason=reason)
        await send_log(interaction.guild, "إجراء إداري: حظر (Ban)",
                      f"بواسطة: {interaction.user.mention}\nالسبب: {reason}",
                      discord.Color.red(), member)
        await interaction.response.send_message(f"✅ تم حظر {member.name} بنجاح.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ البوت لا يملك صلاحية كافية.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {str(e)}", ephemeral=True)

@bot.tree.command(name="ضبط_القائمة", description="إضافة كلمة جديدة لقائمة الممنوعات (Supreme فقط)")
@app_commands.describe(word="الكلمة المراد منعها")
async def add_badword(interaction: discord.Interaction, word: str):
    if not check_rate_limit(interaction.user.id, 10):
        return await interaction.response.send_message("⏳ انتظر.", ephemeral=True)
    if get_user_level(interaction.user) < 3:
        return await interaction.response.send_message("❌ هذا الأمر مخصص لرتبة Supreme فقط.", ephemeral=True)

    try:
        with open('badwords.json', 'r', encoding='utf-8') as f:
            words = json.load(f)
        w = word.strip().lower()
        if w not in words:
            words.append(w)
            with open('badwords.json', 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False, indent=4)
            bot.load_badwords()
            await send_log(interaction.guild, "تحديث النظام",
                          f"تم إضافة كلمة جديدة للقائمة السوداء بواسطة {interaction.user.mention}",
                          discord.Color.blue())
            await interaction.response.send_message("✅ تم إضافة الكلمة وتحديث درع الحماية بنجاح.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ الكلمة موجودة مسبقاً في القائمة.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ حدث خطأ: {str(e)}", ephemeral=True)

@bot.tree.command(name="رسالة", description="إرسال رسالة باستخدام البوت (Admin+)")
@app_commands.describe(channel="القناة المراد الإرسال إليها", message="نص الرسالة")
async def send_msg(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    if not check_rate_limit(interaction.user.id, 5):
        return await interaction.response.send_message("⏳ كثرة الاستخدام! انتظر.", ephemeral=True)
    if get_user_level(interaction.user) < 1:
        return await interaction.response.send_message("❌ لا تملك الصلاحية.", ephemeral=True)

    try:
        msg = await channel.send(message)
        await send_log(interaction.guild, "أمر: إرسال رسالة",
                      f"بواسطة: {interaction.user.mention}\nالقناة: {channel.mention}",
                      discord.Color.blue(), channel=channel)
        await interaction.response.send_message(f"✅ تم الإرسال: {msg.jump_url}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ فشل الإرسال: {str(e)}", ephemeral=True)

@bot.tree.command(name="إزالة_عقوبة", description="إزالة عقوبة عن عضو (Owner+)")
@app_commands.describe(member="العضو", type="نوع العقوبة")
@app_commands.choices(type=[
    app_commands.Choice(name="تايم أوت فقط", value="timeout"),
    app_commands.Choice(name="تحذيرات فقط", value="warn"),
    app_commands.Choice(name="الكل", value="all")
])
async def remove_punishment(interaction: discord.Interaction, member: discord.Member, type: app_commands.Choice[str]):
    if not check_rate_limit(interaction.user.id, 5):
        return await interaction.response.send_message("⏳ انتظر.", ephemeral=True)
    if get_user_level(interaction.user) < 2:
        return await interaction.response.send_message("❌ Owner+ فقط.", ephemeral=True)

    try:
        if type.value in ["timeout", "all"]:
            await member.timeout(None, reason=f"إزالة عقوبة بواسطة {interaction.user}")
        if type.value in ["warn", "all"]:
            user_warnings[member.id] = 0
            user_spam_score[member.id] = 0

        await send_log(interaction.guild, "إزالة عقوبة",
                      f"بواسطة: {interaction.user.mention}\nالنوع: {type.name}\nالعضو: {member.mention}",
                      discord.Color.green(), member)
        await interaction.response.send_message(f"✅ تم إزالة العقوبة ({type.name}) عن {member.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {str(e)}", ephemeral=True)

@bot.tree.command(name="إضافة_عقوبة", description="إضافة عقوبة يدوية (Owner+)")
@app_commands.describe(member="العضو", minutes="عدد الدقائق", reason="السبب")
async def add_punishment(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str):
    if not check_rate_limit(interaction.user.id, 5):
        return await interaction.response.send_message("⏳ انتظر.", ephemeral=True)
    if get_user_level(interaction.user) < 2:
        return await interaction.response.send_message("❌ Owner+ فقط.", ephemeral=True)
    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك معاقبة مسؤول.", ephemeral=True)
    if minutes < 1 or minutes > 40320:
        return await interaction.response.send_message("❌ الحد المسموح: 1 إلى 40320 دقيقة.", ephemeral=True)

    try:
        dur = timedelta(minutes=minutes)
        await member.timeout(dur, reason=f"عقوبة يدوية: {reason}")
        await send_log(interaction.guild, "عقوبة يدوية",
                      f"بواسطة: {interaction.user.mention}\nالسبب: {reason}\nالمدة: {minutes} دقيقة",
                      discord.Color.red(), member)
        await interaction.response.send_message(f"✅ تمت العقوبة بنجاح.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {str(e)}", ephemeral=True)

# ==========================================
# التشغيل
# ==========================================
if __name__ == "__main__":
    keep_alive()
    try:
        bot.run(TOKEN, log_handler=None)
    except Exception as e:
        logger.critical(f"[FATAL] البوت توقف: {e}")
        raise
