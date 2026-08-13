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
from datetime import datetime, timedelta

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
    return jsonify({"status": "Bot is running!", "version": "3.0"}), 200

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

# ---------- نظام مكافحة السبام المتقدم ----------
user_messages = defaultdict(lambda: deque(maxlen=10))  # آخر 10 رسائل لكل مستخدم
message_timestamps = defaultdict(lambda: deque(maxlen=10))
last_message_time = defaultdict(float)  # وقت آخر رسالة من كل مستخدم
SPAM_INTERVAL = 5  # ثواني بين الرسائل
SPAM_WINDOW = 10   # ثواني
SPAM_THRESHOLD = 3  # عدد الرسائل المسموح به في النافذة
SAFE_WORDS = {"سلام", "شكرا", "شكراً", "مرحبا", "اهلا", "هلا"}

def normalize_text(text: str) -> str:
    """تطبيع النص: إزالة التشكيل، توحيد الأحرف"""
    text = text.lower()
    # توحيد الألف
    text = text.replace('إ', 'ا').replace('أ', 'ا').replace('آ', 'ا')
    # توحيد التاء المربوطة
    text = text.replace('ة', 'ه')
    # إزالة علامات الترقيم
    text = re.sub(r'[^\w\s]', '', text)
    return text

def is_safe_word(text: str) -> bool:
    """التحقق من أن النص هو كلمة آمنة (مثل سلام)"""
    normalized = normalize_text(text)
    for word in SAFE_WORDS:
        if word in normalized:
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

def detect_emoji_spam(text: str) -> bool:
    """الكشف عن تكرار الإيموجي المتغير"""
    emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0001FB00-\U0001FBFF\u2600-\u26FF\u2700-\u27BF]+')
    emojis = emoji_pattern.findall(text)
    if len(emojis) >= 5:
        # حساب عدد الإيموجي الفريد والمتكرر
        unique_emojis = set(emojis)
        if len(emojis) / max(1, len(unique_emojis)) >= 2:  # تكرار بنسبة 2:1
            return True
        if len(emojis) >= 8:  # كمية كبيرة جداً
            return True
    return False

def is_spam(text: str, user_id: int) -> bool:
    """الكشف المتقدم عن السبام"""
    current_time = time.time()
    
    # 1. التحقق من التكرار مع اختلاف بسيط (Levenshtein)
    last_messages = user_messages[user_id]
    for prev_msg in last_messages:
        if prev_msg and len(prev_msg) > 3 and len(text) > 3:
            dist = levenshtein_distance(text, prev_msg)
            if dist <= 2 and len(text) > 5:  # تشابه كبير
                return True
    
    # 2. تكرار الإيموجي مع التنويع
    if detect_emoji_spam(text):
        return True
    
    # 3. تكرار الحروف (أكثر من 4)
    if re.search(r'(.)\1{4,}', text):
        return True
    
    # 4. روابط مكررة أو دعوات
    if re.search(r'(discord\.gg/|discord\.com/invite/|free\s+nitro|free\s+robux|click\s+here|join\s+now)', text, re.IGNORECASE):
        return True
    
    # 5. تكرار الإرسال السريع (أكثر من 3 رسائل في 10 ثوانٍ)
    timestamps = message_timestamps[user_id]
    timestamps.append(current_time)
    # حذف الطوابع الأقدم من النافذة
    while timestamps and timestamps[0] < current_time - SPAM_WINDOW:
        timestamps.popleft()
    if len(timestamps) > SPAM_THRESHOLD:
        # استثناء الكلمات الآمنة (مثل سلام)
        if not is_safe_word(text):
            return True
    
    # 6. الفاصل الزمني بين الرسائل (5 ثوانٍ)
    if current_time - last_message_time[user_id] < SPAM_INTERVAL:
        if not is_safe_word(text):
            return True
    
    return False

# ---------- دالة إنشاء صورة الترحيب (بدون تغيير الأبعاد) ----------
async def create_welcome_image(member: discord.Member):
    async with aiohttp.ClientSession() as session:
        async with session.get(WELCOME_BG_URL) as resp:
            if resp.status != 200:
                return None
            bg_data = await resp.read()
    
    # فتح الصورة الخلفية دون تغيير حجمها
    bg = Image.open(BytesIO(bg_data)).convert("RGBA")
    # الحفاظ على الأبعاد الأصلية
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
    avatar_size = int(bg_width * 0.1)  # 10% من عرض الخلفية
    avatar_size = max(60, min(avatar_size, 120))  # بين 60 و 120 بكسل
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
    
    # جعل الصورة دائرية
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)
    
    # وضع الصورة في الزاوية اليمنى العليا مع هامش 5%
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
    last_message_time[user_id] = time.time()
    
    # التحقق من الكلمات السيئة
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

# ---------- أوامر سلاش ----------
@tree.command(name='send', description='أرسل رسالة نصية')
async def send_message(interaction: discord.Interaction, content: str):
    await interaction.response.send_message(content)

@tree.command(name='send_with_image', description='أرسل رسالة مع صورة مرفقة')
async def send_with_image(interaction: discord.Interaction, content: str, image: discord.Attachment):
    file = await image.to_file()
    await interaction.response.send_message(content=content, file=file)

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
