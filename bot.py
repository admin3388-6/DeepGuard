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

# ---------- تحميل الكلمات السيئة من ملف JSON ----------
try:
    with open('badwords.json', 'r', encoding='utf-8') as f:
        RAW_DATA = json.load(f)
        # البنية: { "bad_words_filter": { ... } }
        BAD_WORDS_DATA = RAW_DATA.get('bad_words_filter', RAW_DATA)
except FileNotFoundError:
    print("⚠️ ملف badwords.json غير موجود! سيتم استخدام قائمة فارغة.")
    BAD_WORDS_DATA = {}

# استخراج الفئات والكلمات من الملف فقط (بدون إضافات في الكود)
categories = BAD_WORDS_DATA.get('categories', {})
BAD_WORDS_SET = set()
for category, words in categories.items():
    if isinstance(words, list):
        BAD_WORDS_SET.update(words)

# القائمة البيضاء من filter_settings
filter_settings = BAD_WORDS_DATA.get('filter_settings', {})
WHITELIST = set(filter_settings.get('false_positive_whitelist', []))

# ---------- إعداد Flask (خادم الويب) ----------
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return jsonify({"status": "Bot is running!", "version": "2.0"}), 200

@app_web.route('/ping')
def ping():
    return jsonify({"status": "pong"}), 200

def run_web():
    port = int(os.getenv('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# ---------- إعداد بوت ديسكورد ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# معرفات القنوات
WELCOME_CHANNEL_ID = 1537246493088555038
FILTER_CHANNEL_ID = 1537245866623246416
WELCOME_BG_URL = "https://i.ibb.co/rY0pszN/Police-officers-posing-in-city-202608130017.jpg"

# ---------- دالة لإنشاء صورة الترحيب ----------
async def create_welcome_image(member: discord.Member):
    async with aiohttp.ClientSession() as session:
        async with session.get(WELCOME_BG_URL) as resp:
            if resp.status != 200:
                return None
            bg_data = await resp.read()
    
    bg = Image.open(BytesIO(bg_data)).convert("RGBA")
    bg = bg.resize((800, 400), Image.Resampling.LANCZOS)
    
    avatar_url = member.display_avatar.url
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status != 200:
                return None
            avatar_data = await resp.read()
    
    avatar = Image.open(BytesIO(avatar_data)).convert("RGBA")
    avatar_size = 80
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
    
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)
    
    margin = 15
    bg.paste(avatar, (bg.width - avatar_size - margin, margin), avatar)
    
    img_bytes = BytesIO()
    bg.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

# ---------- حدث عند انضمام عضو ----------
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ القناة {WELCOME_CHANNEL_ID} غير موجودة!")
        return
    
    img_bytes = await create_welcome_image(member)
    if img_bytes is None:
        await channel.send(f" 
        {member.mention} 
        ")
        return
    
    file = discord.File(img_bytes, filename="welcome.png")
    embed = discord.Embed(
        title=f" welcome {member.display_name}!",
        description=" ",
        color=discord.Color.green()
    )
    embed.set_image(url="attachment://welcome.png")
    await channel.send(f"مرحباً {member.mention}", embed=embed, file=file)

# ---------- فلتر الكلمات ----------
def contains_bad_word(text: str) -> bool:
    text_lower = text.lower()
    for bad_word in BAD_WORDS_SET:
        if bad_word.lower() in text_lower:
            # التحقق من القائمة البيضاء
            is_whitelisted = False
            for ww in WHITELIST:
                if bad_word.lower() in ww.lower():
                    is_whitelisted = True
                    break
            if not is_whitelisted:
                return True
    return False

def is_spam(text: str) -> bool:
    if re.search(r'(.)\1{4,}', text):
        return True
    emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0001FB00-\U0001FBFF\u2600-\u26FF\u2700-\u27BF]+')
    emojis = emoji_pattern.findall(text)
    if len(emojis) > 5:
        return True
    if re.search(r'(discord\.gg/|discord\.com/invite/|free\s+nitro|free\s+robux|click\s+here|join\s+now)', text, re.IGNORECASE):
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
    
    if contains_bad_word(message.content):
        await message.delete()
        await message.channel.send(
            f"🚫 {message.author.mention}، تم حذف رسالتك لأنها تحتوي على كلمات غير لائقة.",
            delete_after=5
        )
        return
    
    if is_spam(message.content):
        await message.delete()
        await message.channel.send(
            f"⚠️ {message.author.mention}، تم حذف رسالتك لأنها تعتبر سبام.",
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
