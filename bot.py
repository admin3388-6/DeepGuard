import discord
from discord import app_commands
import os
import threading
import asyncio
from flask import Flask, jsonify

# ---------- إعداد خادم الويب (Flask) ----------
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return jsonify({"status": "Bot is running!"}), 200

@app_web.route('/ping')
def ping():
    return jsonify({"status": "pong"}), 200

def run_web():
    # Render سيحدد المنفذ تلقائياً عبر متغير PORT
    port = int(os.getenv('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# ---------- إعداد بوت ديسكورد ----------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    print(f'✅ البوت {bot.user} أصبح جاهزاً!')
    try:
        synced = await tree.sync()
        print(f'✅ تم مزامنة {len(synced)} أمر/أوامر')
    except Exception as e:
        print(f'❌ خطأ في المزامنة: {e}')

# الأمر الأول: /send (إرسال رسالة نصية)
@tree.command(name='send', description='أرسل رسالة نصية')
async def send_message(interaction: discord.Interaction, content: str):
    await interaction.response.send_message(content)

# الأمر الثاني: /send_with_image (إرسال رسالة مع صورة)
@tree.command(name='send_with_image', description='أرسل رسالة مع صورة مرفقة')
async def send_with_image(interaction: discord.Interaction, content: str, image: discord.Attachment):
    file = await image.to_file()
    await interaction.response.send_message(content=content, file=file)

# ---------- تشغيل البوت وخادم الويب معاً ----------
def run_bot():
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        print(f'❌ خطأ في البوت: {e}')

if __name__ == "__main__":
    # تشغيل خادم الويب في خيط منفصل حتى لا يحجب البوت
    thread = threading.Thread(target=run_web)
    thread.start()
    
    # تشغيل البوت في الخيط الرئيسي
    run_bot()
