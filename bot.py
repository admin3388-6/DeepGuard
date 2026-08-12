import discord
from discord import app_commands
import os

# تفعيل النية اللازمة للبوت لقراءة الرسائل
intents = discord.Intents.default()
intents.message_content = True

# إنشاء كائن البوت
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# حدث عند تشغيل البوت
@bot.event
async def on_ready():
    print(f'البوت {bot.user} أصبح جاهزاً!')
    try:
        # مزامنة أوامر السلاك في السيرفر الخاص بك
        synced = await tree.sync()
        print(f'تم مزامنة {len(synced)} أمر/أوامر')
    except Exception as e:
        print(f'خطأ في المزامنة: {e}')

# الأمر الأول: /send (لإرسال رسالة نصية فقط)
@tree.command(name='send', description='أرسل رسالة نصية')
async def send_message(interaction: discord.Interaction, content: str):
    await interaction.response.send_message(content)

# الأمر الثاني: /send_with_image (لإرسال رسالة مع صورة)
@tree.command(name='send_with_image', description='أرسل رسالة مع صورة مرفقة')
async def send_with_image(interaction: discord.Interaction, content: str, image: discord.Attachment):
    # تحويل الصورة المرفقة إلى ملف يمكن إرساله
    file = await image.to_file()
    await interaction.response.send_message(content=content, file=file)

# تشغيل البوت باستخدام التوكن
bot.run(os.getenv('DISCORD_TOKEN'))
