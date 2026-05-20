import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import re
import asyncio
from collections import defaultdict
from datetime import timedelta
import time
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

# ==========================================
# 🔴 1. الإصلاح الجذري لمشكلة تجمد الاتصال (إجبار IPv4)
# ==========================================
# نقوم بتعديل الطريقة التي يبحث بها بايثون عن العناوين لنجبره على IPv4 فقط
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = new_getaddrinfo
# ==========================================

# ==========================================
# 🌐 2. خادم الويب الشبح (لإرضاء Render و UptimeRobot)
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("📡 DeepGuard Bot is Active and Secure!".encode('utf-8'))
        
    def log_message(self, format, *args):
        pass # إخفاء سجلات الزيارات لكي لا يمتلئ الكونسول

def run_keep_alive():
    # Render يعطينا البورت تلقائياً، وإلا نستخدم 10000
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[SYSTEM] Web Server is active on port {port} (Ready for Render & UptimeRobot)")
    server.serve_forever()

# تشغيل الخادم في مسار جانبي (Thread) لكي لا يوقف عمل البوت
threading.Thread(target=run_keep_alive, daemon=True).start()
# ==========================================

# تحميل المتغيرات البيئية (لحماية التوكن)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("[CRITICAL] لم يتم العثور على توكن البوت! تأكد من إعدادات Render.")

# ==========================================
# الإعدادات الأساسية (القنوات والرتب)
# ==========================================
CONTROL_CHANNEL_ID = 1506420018890543114
LOG_CHANNEL_ID = 1506420345387876402

IGNORED_CHANNELS = {
    1504557542825529374,
    1504556508103577743,
    1497648145666932826,
    1497621523639570524
}

# الرتب والصلاحيات
SUPREME_ROLES = {1505681669418647594, 1497618182763053096}
OWNER_ROLES = {1497646073060003982}
ADMIN_ROLES = {1504544220030173265, 1504575260563865681}

# ==========================================
# إعدادات الفلترة والحماية
# ==========================================
ALLOWED_DOMAINS = [
    "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "linkedin.com", "twitch.tv",
    "cdn.discordapp.com", "media.discordapp.net", "warera.com"
]

SHORTENER_DOMAINS = [
    "bit.ly", "goo.gl", "tinyurl.com", "t.co", "cutt.ly", "is.gd", "buff.ly"
]

URL_REGEX = re.compile(r'(https?://[^\s]+)')

user_messages_cache = defaultdict(list)
user_warnings = defaultdict(int)

# ==========================================
# تجهيز البوت
# ==========================================
class DeepGuard(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.badwords_patterns = []
        self.load_badwords()

    def load_badwords(self):
        try:
            with open('badwords.json', 'r', encoding='utf-8') as f:
                words = json.load(f)
                self.badwords_patterns = []
                for word in words:
                    pattern_str = r'[\W_]*'.join(list(word))
                    self.badwords_patterns.append(re.compile(pattern_str, re.IGNORECASE))
            print(f"[SHIELD] تم تحميل {len(self.badwords_patterns)} كلمة وإعداد درع الحماية الذكي.")
        except FileNotFoundError:
            print("[WARNING] ملف badwords.json غير موجود. سيتم إنشاء ملف فارغ.")
            with open('badwords.json', 'w', encoding='utf-8') as f:
                json.dump([], f)

bot = DeepGuard()

# ==========================================
# دوال مساعدة (Helper Functions)
# ==========================================
def get_user_level(member: discord.Member) -> int:
    role_ids = {role.id for role in member.roles}
    if role_ids.intersection(SUPREME_ROLES) or member.guild.owner_id == member.id:
        return 3
    if role_ids.intersection(OWNER_ROLES):
        return 2
    if role_ids.intersection(ADMIN_ROLES):
        return 1
    return 0

async def send_log(guild: discord.Guild, title: str, description: str, color: discord.Color, member: discord.Member = None, message_link: str = None):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
    if member:
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="المستخدم", value=f"{member.mention} ({member.id})", inline=False)
    if message_link:
        embed.add_field(name="رابط الرسالة", value=f"[اضغط هنا للانتقال]({message_link})", inline=False)
    
    await channel.send(embed=embed)

async def auto_punish(member: discord.Member, reason: str):
    user_warnings[member.id] += 1
    warnings = user_warnings[member.id]

    if warnings >= 3:
        try:
            duration = timedelta(hours=1)
            await member.timeout(duration, reason=f"تجاوز الحد الأقصى للتحذيرات (السبب الأخير: {reason})")
            await send_log(member.guild, "عقوبة تلقائية: تيم أوت", f"تم إعطاء تيم أوت للعضو لمدة ساعة لتكرار المخالفات.\nالسبب: {reason}", discord.Color.orange(), member)
            user_warnings[member.id] = 0
        except Exception:
            pass
    else:
        try:
            await member.send(f"⚠️ **تحذير من نظام DeepGuard:** تم تسجيل مخالفة ضدك. السبب: {reason}. (التحذير رقم {warnings}/3)")
            await send_log(member.guild, "مراقبة: تحذير تلقائي", f"تم تحذير العضو. السبب: {reason} ({warnings}/3)", discord.Color.yellow(), member)
        except Exception:
            pass

# ==========================================
# الأحداث (Events)
# ==========================================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'[SYSTEM] Logged in successfully as {bot.user} - DeepGuard is ACTIVE!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="السيرفر بصرامة"))

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id in IGNORED_CHANNELS:
        return

    user_level = get_user_level(message.author)
    
    if user_level > 0:
        return

    content = message.content
    now = time.time()
    
    user_cache = user_messages_cache[message.author.id]
    user_cache.append(now)
    user_messages_cache[message.author.id] = [t for t in user_cache if now - t <= 10]
    
    if len(user_messages_cache[message.author.id]) >= 4:
        await message.delete()
        await auto_punish(message.author, "سبام وإرسال رسائل متكررة بسرعة")
        return

    urls = URL_REGEX.findall(content)
    if urls:
        is_bad_link = False
        for url in urls:
            url_lower = url.lower()
            if "discord.gg/" in url_lower or "discord.com/invite/" in url_lower:
                is_bad_link = True
                break
            if any(shortener in url_lower for shortener in SHORTENER_DOMAINS):
                is_bad_link = True
                break
            if not any(domain in url_lower for domain in ALLOWED_DOMAINS):
                is_bad_link = True
                break
        
        if is_bad_link:
            await message.delete()
            await auto_punish(message.author, "إرسال روابط غير مصرح بها أو دعوات سيرفرات")
            return

    for pattern in bot.badwords_patterns:
        if pattern.search(content):
            await message.delete()
            await auto_punish(message.author, "استخدام ألفاظ نابية أو مشفرة")
            return

# ==========================================
# الأوامر (Slash Commands)
# ==========================================
@bot.tree.command(name="تنبيه", description="إرسال تحذير رسمي لعضو")
@app_commands.describe(member="العضو", reason="السبب")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if get_user_level(interaction.user) < 1:
        return await interaction.response.send_message("❌ لا تملك الصلاحية لاستخدام هذا الأمر.", ephemeral=True)
    
    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك معاقبة شخص برتبة مساوية أو أعلى منك.", ephemeral=True)

    await auto_punish(member, f"تحذير إداري: {reason}")
    await interaction.response.send_message(f"✅ تم توجيه تحذير إلى {member.mention} بنجاح.", ephemeral=True)

@bot.tree.command(name="تيم_أوت", description="إعطاء العضو timeout")
@app_commands.describe(member="العضو", minutes="عدد الدقائق", reason="السبب")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "بدون سبب"):
    if get_user_level(interaction.user) < 1:
        return await interaction.response.send_message("❌ لا تملك الصلاحية لاستخدام هذا الأمر.", ephemeral=True)

    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك معاقبة شخص برتبة مساوية أو أعلى منك.", ephemeral=True)

    try:
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await send_log(interaction.guild, "إجراء إداري: تيم أوت", f"بواسطة: {interaction.user.mention}\nالسبب: {reason}\nالمدة: {minutes} دقيقة", discord.Color.orange(), member)
        await interaction.response.send_message(f"✅ تم إعطاء تيم أوت لـ {member.mention} لمدة {minutes} دقيقة.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ البوت لا يملك صلاحية كافية (تأكد من ترتيب رتبة البوت).", ephemeral=True)

@bot.tree.command(name="مسح", description="حذف عدد من الرسائل (للرتب العليا فقط)")
@app_commands.describe(amount="عدد الرسائل")
async def purge(interaction: discord.Interaction, amount: int):
    if get_user_level(interaction.user) < 2: 
        return await interaction.response.send_message("❌ هذا الأمر مخصص للرتب العليا فقط.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await send_log(interaction.guild, "إجراء إداري: مسح رسائل", f"تم مسح {len(deleted)} رسالة في {interaction.channel.mention}\nبواسطة: {interaction.user.mention}", discord.Color.light_grey())
    await interaction.followup.send(f"✅ تم مسح {len(deleted)} رسائل بنجاح.")

@bot.tree.command(name="حظر", description="حظر العضو من السيرفر (للرتب العليا فقط)")
@app_commands.describe(member="العضو", reason="السبب")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    if get_user_level(interaction.user) < 2: 
        return await interaction.response.send_message("❌ هذا الأمر مخصص للرتب العليا فقط.", ephemeral=True)

    if get_user_level(member) >= get_user_level(interaction.user):
        return await interaction.response.send_message("❌ لا يمكنك حظر شخص برتبة مساوية أو أعلى منك.", ephemeral=True)

    try:
        await member.ban(reason=reason)
        await send_log(interaction.guild, "إجراء إداري: حظر (Ban)", f"بواسطة: {interaction.user.mention}\nالسبب: {reason}", discord.Color.red(), member)
        await interaction.response.send_message(f"✅ تم حظر {member.name} بنجاح.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ البوت لا يملك صلاحية كافية.", ephemeral=True)

@bot.tree.command(name="ضبط_القائمة", description="إضافة كلمة جديدة لقائمة الممنوعات (Supreme فقط)")
@app_commands.describe(word="الكلمة المراد منعها")
async def add_badword(interaction: discord.Interaction, word: str):
    if get_user_level(interaction.user) < 3: 
        return await interaction.response.send_message("❌ هذا الأمر مخصص لرتبة Supreme فقط.", ephemeral=True)

    try:
        with open('badwords.json', 'r', encoding='utf-8') as f:
            words = json.load(f)
        
        if word not in words:
            words.append(word)
            with open('badwords.json', 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False, indent=4)
            
            bot.load_badwords()
            await send_log(interaction.guild, "تحديث النظام", f"تم إضافة كلمة جديدة للقائمة السوداء بواسطة {interaction.user.mention}", discord.Color.blue())
            await interaction.response.send_message(f"✅ تم إضافة الكلمة وتحديث درع الحماية بنجاح.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ الكلمة موجودة مسبقاً في القائمة.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ حدث خطأ: {str(e)}", ephemeral=True)

if TOKEN:
    print("[SYSTEM] جاري بدء الاتصال مع ديسكورد...")
    bot.run(TOKEN)
