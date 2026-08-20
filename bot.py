import discord
from discord import app_commands
import os
import json
import re
import asyncio
from flask import Flask, jsonify
import threading
from io import BytesIO
from PIL import Image, ImageDraw
import aiohttp
from collections import defaultdict, deque
import time

# ---------- تحميل الكلمات السيئة ----------
try:
    with open('badwords.json', 'r', encoding='utf-8') as f:
        RAW_DATA = json.load(f)
        BAD_WORDS_DATA = RAW_DATA.get('bad_words_filter', RAW_DATA)
except FileNotFoundError:
    print("⚠️ ملف badwords.json غير موجود!")
    BAD_WORDS_DATA = {}

categories = BAD_WORDS_DATA.get('categories', {})
BAD_WORDS_SET = set()
for category, words in categories.items():
    if isinstance(words, list):
        BAD_WORDS_SET.update(words)

filter_settings = BAD_WORDS_DATA.get('filter_settings', {})
WHITELIST = set(filter_settings.get('false_positive_whitelist', []))

# ---------- إعداد Flask ----------
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return jsonify({"status": "Bot is running!", "version": "3.2"}), 200

@app_web.route('/ping')
def ping():
    return jsonify({"status": "pong"}), 200

def run_web():
    port = int(os.getenv('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# ---------- إعداد البوت ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

WELCOME_CHANNEL_ID = 1537246493088555038
FILTER_CHANNEL_ID = 1537245866623246416
WELCOME_BG_URL = "https://i.ibb.co/rY0pszN/Police-officers-posing-in-city-202608130017.jpg"

# ---------- نظام مكافحة السبام المتقدم (أقل صرامة) ----------
user_messages = defaultdict(lambda: deque(maxlen=10))  # آخر 10 رسائل لكل مستخدم
user_timestamps = defaultdict(lambda: deque(maxlen=10))

def is_spam(text: str, user_id: int) -> bool:
    """الكشف عن السبام الواضح فقط"""
    # 1. تجاهل الرسائل القصيرة جداً (أقل من 3 أحرف)
    if len(text.strip()) < 3:
        return False
    
    # 2. الكشف عن تكرار الإيموجي بكثافة عالية (أكثر من 10 إيموجي)
    emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0001FB00-\U0001FBFF\u2600-\u26FF\u2700-\u27BF]+')
    emojis = emoji_pattern.findall(text)
    if len(emojis) >= 10:
        return True
    
    # 3. الكشف عن تكرار الرسائل المتطابقة أو المتشابهة جداً في وقت قصير
    current_time = time.time()
    user_timestamps[user_id].append(current_time)
    
    # تنظيف الطوابع الأقدم من 10 ثوانٍ
    while user_timestamps[user_id] and user_timestamps[user_id][0] < current_time - 10:
        user_timestamps[user_id].popleft()
    
    # إذا أرسل المستخدم أكثر من 5 رسائل في 10 ثوانٍ
    if len(user_timestamps[user_id]) >= 5:
        # التحقق من تشابه الرسائل
        last_messages = list(user_messages[user_id])
        if len(last_messages) >= 5:
            # حساب عدد الرسائل المتطابقة (نفس النص تماماً)
            identical_count = sum(1 for msg in last_messages if msg == text)
            if identical_count >= 3:
                return True
            # حساب عدد الرسائل المتشابهة جداً (مسافة Levenshtein <= 2)
            similar_count = 0
            for msg in last_messages:
                if len(msg) > 3 and len(text) > 3:
                    dist = levenshtein_distance(text, msg)
                    if dist <= 2:
                        similar_count += 1
            if similar_count >= 4:
                return True
    
    # 4. روابط مشبوهة (دعوات سيرفر، إعلانات)
    if re.search(r'(discord\.gg/|discord\.com/invite/|free\s+nitro|free\s+robux|click\s+here|join\s+now)', text, re.IGNORECASE):
        return True
    
    return False

def levenshtein_distance(s1: str, s2: str) -> int:
    """حساب مسافة التعديل بين نصين (بسيط)"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

# ---------- دالة إنشاء صورة الترحيب (بدون تغيير الأبعاد) ----------
async def create_welcome_image(member: discord.Member):
    async with aiohttp.ClientSession() as session:
        async with session.get(WELCOME_BG_URL) as resp:
            if resp.status != 200:
                return None
            bg_data = await resp.read()
    
    # فتح الصورة الخلفية دون تغيير حجمها
    bg = Image.open(BytesIO(bg_data)).convert("RGBA")
    bg_width, bg_height = bg.size
    
    # جلب صورة الملف الشخصي
    avatar_url = member.display_avatar.url
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status != 200:
                return None
            avatar_data = await resp.read()
    
    avatar = Image.open(BytesIO(avatar_data)).convert("RGBA")
    # حجم الصورة الرمزية (نسبة من عرض الخلفية)
    avatar_size = int(bg_width * 0.1)  # 10% من العرض
    avatar_size = max(60, min(avatar_size, 120))  # بين 60 و 120 بكسل
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
    
    # جعل الصورة دائرية
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)
    
    # وضع الصورة في الزاوية اليمنى العليا مع هامش 2%
    margin = int(bg_width * 0.02)
    bg.paste(avatar, (bg_width - avatar_size - margin, margin), avatar)
    
    img_bytes = BytesIO()
    bg.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

# ---------- حدث انضمام عضو ----------
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ القناة {WELCOME_CHANNEL_ID} غير موجودة!")
        return
    
    img_bytes = await create_welcome_image(member)
    if img_bytes is None:
        msg = await channel.send(f"welcome {member.mention}")
        await msg.add_reaction('👋')
        return
    
    file = discord.File(img_bytes, filename="welcome.png")
    msg = await channel.send(content=f"welcome {member.mention}", file=file)
    await msg.add_reaction('👋')

# ---------- فلتر الكلمات السيئة ----------
def contains_bad_word(text: str) -> bool:
    text_lower = text.lower()
    for bad_word in BAD_WORDS_SET:
        if bad_word.lower() in text_lower:
            is_whitelisted = False
            for ww in WHITELIST:
                if bad_word.lower() in ww.lower():
                    is_whitelisted = True
                    break
            if not is_whitelisted:
                return True
    return False

# ---------- مراقبة الرسائل ----------
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id != FILTER_CHANNEL_ID:
        return
    if message.content.startswith('/'):
        return
    
    # تحديث بيانات المستخدم
    user_id = message.author.id
    user_messages[user_id].append(message.content)
    
    # التحقق من الكلمات السيئة أولاً
    if contains_bad_word(message.content):
        await message.delete()
        await message.channel.send(
            f"🚫 {message.author.mention}، تم حذف رسالتك لأنها تحتوي على كلمات غير لائقة.",
            delete_after=5
        )
        return
    
    # التحقق من السبام
    if is_spam(message.content, user_id):
        await message.delete()
        await message.channel.send(
            f"⚠️ {message.author.mention}، تم حذف رسالتك لأنها تعتبر سبام (إرسال متكرر أو إيموجي مفرط).",
            delete_after=5
        )
        return

# ---------- أوامر سلاش النصية المعدلة ----------
@tree.command(name='send', description='أرسل رسالة نصية')
async def send_message(interaction: discord.Interaction, content: str):
    await interaction.response.defer()
    await interaction.followup.send(content)

@tree.command(name='send_with_image', description='أرسل رسالة مع صورة مرفقة')
async def send_with_image(interaction: discord.Interaction, content: str, image: discord.Attachment):
    await interaction.response.defer()
    file = await image.to_file()
    await interaction.followup.send(content=content, file=file)

# ---------- أمر إرسال الإيمبد الاحترافي ----------
@tree.command(name='send_embed', description='إرسال رسالة إيمبد احترافية مخصصة بالكامل مع صور متعددة')
@app_commands.describe(
    title="عنوان الإيمبد الرئيسي (اختياري)",
    description="وصف أو محتوى الإيمبد (اختياري)",
    color="كود اللون (مثال: #ff0000 أو ff0000 للون الأحمر) (اختياري)",
    author_name="اسم الكاتب (يظهر أعلى الإيمبد) (اختياري)",
    author_icon="أيقونة الكاتب (صورة صغيرة بالأعلى) (اختياري)",
    thumbnail="صورة مصغرة (تظهر على يمين أو يسار الإيمبد) (اختياري)",
    main_image="الصورة الرئيسية (صورة كبيرة أسفل النص) (اختياري)",
    footer_text="نص التذييل (يظهر أسفل الإيمبد) (اختياري)",
    footer_icon="أيقونة التذييل (صورة صغيرة بالأسفل) (اختياري)"
)
async def send_embed(
    interaction: discord.Interaction,
    title: str = None,
    description: str = None,
    color: str = None,
    author_name: str = None,
    author_icon: discord.Attachment = None,
    thumbnail: discord.Attachment = None,
    main_image: discord.Attachment = None,
    footer_text: str = None,
    footer_icon: discord.Attachment = None
):
    await interaction.response.defer()

    embed_color = discord.Color.default()
    if color:
        try:
            color_hex = color.replace("#", "")
            embed_color = discord.Color(int(color_hex, 16))
        except ValueError:
            pass

    if not title and not description:
        await interaction.followup.send("❌ يجب إدخال `title` (عنوان) أو `description` (وصف) على الأقل لإنشاء الإيمبد.", ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description, color=embed_color)

    if author_name:
        icon_url = author_icon.url if author_icon else None
        embed.set_author(name=author_name, icon_url=icon_url)
    elif author_icon:
        embed.set_author(name="\u200b", icon_url=author_icon.url)

    if thumbnail:
        embed.set_thumbnail(url=thumbnail.url)

    if main_image:
        embed.set_image(url=main_image.url)

    if footer_text:
        f_icon_url = footer_icon.url if footer_icon else None
        embed.set_footer(text=footer_text, icon_url=f_icon_url)
    elif footer_icon:
        embed.set_footer(text="\u200b", icon_url=footer_icon.url)

    await interaction.followup.send(embed=embed)

# ---------- حدث الجاهزية ----------
@bot.event
async def on_ready():
    print(f'✅ البوت {bot.user} أصبح جاهزاً!')
    try:
        synced = await tree.sync()
        print(f'✅ تم مزامنة {len(synced)} أمر/أوامر')
    except Exception as e:
        print(f'❌ خطأ في المزامنة: {e}')

# ---------- التشغيل ----------
def run_bot():
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        print(f'❌ خطأ في البوت: {e}')

if __name__ == "__main__":
    thread = threading.Thread(target=run_web)
    thread.start()
    run_bot()
