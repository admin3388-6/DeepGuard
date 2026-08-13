import discord
from discord import app_commands
import os
import json
import re
import asyncio
from flask import Flask, jsonify
import threading
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter
import aiohttp

# ---------- تحميل الكلمات السيئة من ملف JSON ----------
with open('badwords.json', 'r', encoding='utf-8') as f:
    BAD_WORDS_DATA = json.load(f)

# استخراج جميع الكلمات في قائمة واحدة للبحث السريع
BAD_WORDS_SET = set()
for category, words in BAD_WORDS_DATA['categories'].items():
    if isinstance(words, list):
        BAD_WORDS_SET.update(words)

# إضافة كلمات إضافية من نهاية الملف (التي لم تكن ضمن الفئات)
extra_words = [
    "عاهرة", "عاهرات", "فاجر", "فاجرة", "خول", "خولين", "خولات",
    "قحبة", "قحاب", "شرموط", "شرمطة", "منيوك", "منيوكة",
    "كس أمك", "كسمك", "كسمها", "كسومك", "طيزي", "طيزك", "طيزها",
    "زبي", "زبار", "زبه", "احة", "أحة", "أحا", "يري", "يوري",
    "انيك", "نيكك", "نيكي", "فشخته", "فشختك", "يلعن دين", "يلعن شرف",
    "انقلع يلا", "اقلع يلا", "اطلع يلا", "خرج برا",
    "سكس فون", "سكس شات", "قوادين", "قوادي",
    "صهين", "صهينة", "يهودي قذر", "يهود وسخ",
    "رافض", "روفض", "نازي وسخ", "نازية قذرة",
    "عنصري قذر", "عنصرية وسخة", "زنا محارم", "زنا الاخت",
    "fucker bitch", "motherfucking shit", "cunt asshole", "fucking fucker",
    "black nigger", "dirty nigger", "retard fuck", "stupid cunt",
    "يا ابن المتناكة", "يا ابن القحبة", "ابن الشرموطة", "ابن العاهرة",
    "يلعن ابو الدين", "يلعن ام الشرف", "يلعن ابو البيض", "يلعن ام السواد"
]
BAD_WORDS_SET.update(extra_words)

# قائمة بالكلمات المسموحة (لتفادي الحظر الخاطئ)
WHITELIST = set(BAD_WORDS_DATA.get('filter_settings', {}).get('false_positive_whitelist', []))

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
intents.members = True  # ضروري لاستقبال حدث member_join

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# معرفات القنوات (ضعها كما هي)
WELCOME_CHANNEL_ID = 1537246493088555038
FILTER_CHANNEL_ID = 1537245866623246416

# رابط الصورة الخلفية للترحيب
WELCOME_BG_URL = "https://i.ibb.co/rY0pszN/Police-officers-posing-in-city-202608130017.jpg"

# ---------- دالة لإنشاء صورة الترحيب ----------
async def create_welcome_image(member: discord.Member):
    """توليد صورة ترحيبية مع صورة الملف الشخصي في الزاوية اليمنى العليا (صغيرة)"""
    async with aiohttp.ClientSession() as session:
        async with session.get(WELCOME_BG_URL) as resp:
            if resp.status != 200:
                return None
            bg_data = await resp.read()
    
    # تحميل الصورة الخلفية
    bg = Image.open(BytesIO(bg_data)).convert("RGBA")
    
    # تغيير حجم الخلفية إلى حجم مناسب (مثلاً 800x400)
    bg = bg.resize((800, 400), Image.Resampling.LANCZOS)
    
    # جلب صورة الملف الشخصي للعضو
    avatar_url = member.display_avatar.url
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status != 200:
                return None
            avatar_data = await resp.read()
    
    avatar = Image.open(BytesIO(avatar_data)).convert("RGBA")
    
    # تغيير حجم الصورة الرمزية (صغيرة ~ 80x80)
    avatar_size = 80
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
    
    # جعل الصورة دائرية (Mask)
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar.putalpha(mask)
    
    # وضع الصورة الرمزية في الزاوية اليمنى العليا مع هامش 15 بكسل
    margin = 15
    bg.paste(avatar, (bg.width - avatar_size - margin, margin), avatar)
    
    # تحويل الصورة إلى bytes
    img_bytes = BytesIO()
    bg.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

# ---------- حدث عند انضمام عضو جديد ----------
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ القناة {WELCOME_CHANNEL_ID} غير موجودة!")
        return
    
    # إنشاء صورة الترحيب
    img_bytes = await create_welcome_image(member)
    if img_bytes is None:
        # فشل إنشاء الصورة، نرسل رسالة نصية عادية
        await channel.send(f"🎉 مرحباً {member.mention} في السيرفر! نتمنى لك قضاء وقت ممتع.")
        return
    
    # إرسال الصورة مع رسالة ترحيب
    file = discord.File(img_bytes, filename="welcome.png")
    embed = discord.Embed(
        title=f"🎉 مرحباً {member.display_name}!",
        description="نحن سعداء بانضمامك إلى مجتمعنا! 🥳\nاقرأ القوانين واستمتع.",
        color=discord.Color.green()
    )
    embed.set_image(url="attachment://welcome.png")
    await channel.send(f"مرحباً {member.mention}", embed=embed, file=file)

# ---------- فلتر الكلمات السيئة ----------
def contains_bad_word(text: str) -> bool:
    """التحقق من وجود كلمات سيئة في النص مع مراعاة القائمة البيضاء"""
    text_lower = text.lower()
    # التحقق من القائمة البيضاء أولاً
    for whitelist_word in WHITELIST:
        if whitelist_word.lower() in text_lower:
            # إذا احتوى النص على كلمة بيضاء، نتحقق إن كانت الكلمة السيئة جزءاً منها
            # هنا نطبق منطق بسيط: نستثني الكلمات البيضاء
            pass
    
    # نبحث عن أي كلمة سيئة
    for bad_word in BAD_WORDS_SET:
        if bad_word.lower() in text_lower:
            # تأكد من أنها ليست جزءاً من كلمة بيضاء (مثال: "class" تحتوي على "ass")
            # نتحقق إن كانت الكلمة كاملة أو معزولة (نستخدم حدود الكلمات)
            pattern = r'\b' + re.escape(bad_word.lower()) + r'\b'
            if re.search(pattern, text_lower):
                return True
            # أيضاً نبحث عن الكلمات دون حدود (للكلمات المركبة مثل "fucker bitch")
            elif bad_word.lower() in text_lower:
                # نتحقق إن كانت جزءاً من كلمة بيضاء
                is_whitelisted = False
                for ww in WHITELIST:
                    if bad_word.lower() in ww.lower():
                        is_whitelisted = True
                        break
                if not is_whitelisted:
                    return True
    return False

def is_spam(text: str) -> bool:
    """الكشف عن الرسائل المزعجة (تكرار الإيموجي، تكرار الحروف، روابط)"""
    # تكرار الحروف أكثر من 4 مرات متتالية
    if re.search(r'(.)\1{4,}', text):
        return True
    # تكرار الإيموجي (أكثر من 5 إيموجي متتالية)
    emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U0001FB00-\U0001FBFF\u2600-\u26FF\u2700-\u27BF]+')
    emojis = emoji_pattern.findall(text)
    if len(emojis) > 5:
        return True
    # روابط مشبوهة (دعوات، إعلانات)
    if re.search(r'(discord\.gg/|discord\.com/invite/|free\s+nitro|free\s+robux|click\s+here|join\s+now)', text, re.IGNORECASE):
        return True
    return False

# ---------- حدث عند كل رسالة (مراقبة القناة المحددة) ----------
@bot.event
async def on_message(message):
    # تجاهل رسائل البوت نفسه
    if message.author == bot.user:
        return
    
    # فقط في القناة المخصصة للفلتر
    if message.channel.id != FILTER_CHANNEL_ID:
        return
    
    # تجاهل الأوامر (تبدأ بـ /)
    if message.content.startswith('/'):
        return
    
    # التحقق من الكلمات السيئة
    if contains_bad_word(message.content):
        await message.delete()
        await message.channel.send(
            f"🚫 {message.author.mention}، تم حذف رسالتك لأنها تحتوي على كلمات غير لائقة.",
            delete_after=5
        )
        return
    
    # التحقق من السبام
    if is_spam(message.content):
        await message.delete()
        await message.channel.send(
            f"⚠️ {message.author.mention}، تم حذف رسالتك لأنها تعتبر سبام (إيموجي مكرر أو روابط).",
            delete_after=5
        )
        return

# ---------- أوامر /سلاش (إرسال رسائل) ----------
@tree.command(name='send', description='أرسل رسالة نصية')
async def send_message(interaction: discord.Interaction, content: str):
    await interaction.response.send_message(content)

@tree.command(name='send_with_image', description='أرسل رسالة مع صورة مرفقة')
async def send_with_image(interaction: discord.Interaction, content: str, image: discord.Attachment):
    file = await image.to_file()
    await interaction.response.send_message(content=content, file=file)

# ---------- حدث عند تشغيل البوت ----------
@bot.event
async def on_ready():
    print(f'✅ البوت {bot.user} أصبح جاهزاً!')
    try:
        synced = await tree.sync()
        print(f'✅ تم مزامنة {len(synced)} أمر/أوامر')
    except Exception as e:
        print(f'❌ خطأ في المزامنة: {e}')

# ---------- تشغيل البوت وخادم الويب معاً ----------
def run_bot():
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        print(f'❌ خطأ في البوت: {e}')

if __name__ == "__main__":
    # تشغيل خادم الويب في خيط منفصل
    thread = threading.Thread(target=run_web)
    thread.start()
    # تشغيل البوت
    run_bot()
