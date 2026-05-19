import nextcord
from nextcord.ext import commands
from nextcord import Interaction, SlashOption
import json
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict, deque

# ==================== التكوين ====================
with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

with open("badwords.json", "r", encoding="utf-8") as f:
    BAD_WORDS = set(json.load(f))

# ==================== الثوابت ====================
TOKEN = os.getenv("DEEPGUARD_TOKEN")
if not TOKEN:
    raise ValueError("❌ متغير البيئة DEEPGUARD_TOKEN غير محدد!")

LOG_CHANNEL_ID = int(cfg["log_channel_id"])
CONTROL_CHANNEL_ID = int(cfg["control_channel_id"])
IGNORED_CHANNELS = [int(x) for x in cfg["ignored_channels"]]

SUPREME_ROLES = [int(x) for x in cfg["roles"]["supreme"]]
OWNER_ROLES = [int(x) for x in cfg["roles"]["owner"]]
ADMIN_ROLES = [int(x) for x in cfg["roles"]["admin"]]
ALL_ADMIN_ROLES = SUPREME_ROLES + OWNER_ROLES + ADMIN_ROLES

ALLOWED_DOMAINS = set(cfg["allowed_domains"])
SHORTENERS = set(cfg["url_shorteners"])

# ==================== الكاش الخفيف ====================
message_cache = defaultdict(lambda: deque(maxlen=50))
warn_counts = defaultdict(int)
muted_users = set()

# ==================== المساعدات ====================
def has_any_role(member, role_ids):
    return any(r.id in role_ids for r in member.roles)

def is_immune(member):
    return has_any_role(member, SUPREME_ROLES + OWNER_ROLES)

def is_admin(member):
    return has_any_role(member, ALL_ADMIN_ROLES)

def is_supreme(member):
    return has_any_role(member, SUPREME_ROLES)

def is_owner(member):
    return has_any_role(member, OWNER_ROLES)

def get_top_role_power(member):
    if is_supreme(member): return 3
    if is_owner(member): return 2
    if has_any_role(member, ADMIN_ROLES): return 1
    return 0

def normalize_arabic(text):
    text = text.lower()
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي',
        'ؤ': 'و', 'ئ': 'ي', 'ة': 'ه',
        '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '9': 'g',
        '@': 'a', '$': 's', '!': 'i',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def contains_bad_word(text):
    normalized = normalize_arabic(text)
    words = re.findall(r'[\w]+', normalized)
    for w in words:
        if w in BAD_WORDS:
            return True
    for bw in BAD_WORDS:
        if len(bw) >= 3 and bw in normalized:
            return True
    return False

def extract_domains(text):
    pattern = r'https?://([^/\s]+)'
    return re.findall(pattern, text)

def is_url_allowed(text):
    domains = extract_domains(text)
    if not domains:
        return True
    for domain in domains:
        d = domain.lower().replace("www.", "")
        if any(s in d for s in SHORTENERS):
            return False
        allowed = False
        for ad in ALLOWED_DOMAINS:
            if ad in d or d.endswith(ad):
                allowed = True
                break
        if not allowed:
            return False
    return True

def is_invite_link(text):
    return bool(re.search(r'discord\.(gg|com/invite)\/[^\s]+', text, re.I))

async def send_log(guild, title, description, color, fields=None, target_member=None):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if not ch:
        return
    emb = nextcord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    if fields:
        for k, v in fields.items():
            emb.add_field(name=k, value=v, inline=False)
    if target_member:
        emb.set_thumbnail(url=target_member.display_avatar.url)
    await ch.send(embed=emb)

async def apply_timeout(member, guild, minutes, reason):
    try:
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await send_log(
            guild,
            "⏱️ Timeout",
            f"{member.mention} تم وضعه في تيم أوت",
            0xffa500,
            {"السبب": reason, "المدة": f"{minutes} دقيقة"},
            member
        )
    except Exception as e:
        print(f"[Punish Error] timeout: {e}")

# ==================== البوت ====================
intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    max_messages=1000
)

@bot.event
async def on_ready():
    print(f"[DeepGuard] Logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.watching, name="over the server"))
    try:
        synced = await bot.sync_all_application_commands()
        print(f"[DeepGuard] Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"[DeepGuard] Sync error: {e}")
    for guild in bot.guilds:
        log_ch = guild.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            emb = nextcord.Embed(
                title="🛡️ DeepGuard Online",
                description="البوت يعمل الآن في الوضع الآمن على 1 جيجا رام",
                color=0x00ff00,
                timestamp=datetime.utcnow()
            )
            await log_ch.send(embed=emb)
            break

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not message.guild:
        return
    if message.channel.id in IGNORED_CHANNELS:
        return
    member = message.author
    if is_immune(member):
        return

    content = message.content
    deleted = False

    # 1. كلمات شتيمة
    if contains_bad_word(content):
        try:
            await message.delete()
            deleted = True
            warn_counts[member.id] += 1
            await send_log(
                message.guild,
                "🚫 كلمة ممنوعة",
                f"تم حذف رسالة من {member.mention}",
                0xff0033,
                {"العضو": member.mention, "المحتوى": content[:500], "القناة": message.channel.mention},
                member
            )
            if warn_counts[member.id] >= 3:
                await apply_timeout(member, message.guild, 10, "تجاوز 3 تحذيرات (شتائم)")
        except Exception as e:
            print(f"[Filter Error] delete badword: {e}")

    # 2. روابط ضارة
    if not deleted and (not is_url_allowed(content) or is_invite_link(content)):
        try:
            await message.delete()
            deleted = True
            warn_counts[member.id] += 1
            await send_log(
                message.guild,
                "🔗 رابط ممنوع",
                f"تم حذف رسالة تحتوي رابطاً غير مصرح به",
                0xff6600,
                {"العضو": member.mention, "المحتوى": content[:500], "القناة": message.channel.mention},
                member
            )
            if warn_counts[member.id] >= 3:
                await apply_timeout(member, message.guild, 10, "تجاوز 3 تحذيرات (روابط)")
        except Exception as e:
            print(f"[Filter Error] delete link: {e}")

    # 3. سبام / تكرار
    if not deleted:
        cache = message_cache[member.id]
        cache.append({"content": content, "time": datetime.utcnow(), "channel": message.channel.id})
        
        recent = [m for m in cache if (datetime.utcnow() - m["time"]).total_seconds() <= 10]
        same_msg = [m for m in recent if m["content"] == content]
        if len(same_msg) >= 3:
            try:
                await message.delete()
                warn_counts[member.id] += 1
                await send_log(
                    message.guild,
                    "⚠️ سبام",
                    f"تكرار نفس الرسالة 3 مرات في 10 ثوانٍ",
                    0xffaa00,
                    {"العضو": member.mention, "القناة": message.channel.mention},
                    member
                )
                if warn_counts[member.id] >= 3:
                    await apply_timeout(member, message.guild, 15, "تجاوز 3 تحذيرات (سبام)")
            except Exception as e:
                print(f"[Filter Error] delete spam: {e}")

        very_recent = [m for m in cache if (datetime.utcnow() - m["time"]).total_seconds() <= 5]
        if len(very_recent) >= 5:
            try:
                await message.delete()
                warn_counts[member.id] += 1
                await send_log(
                    message.guild,
                    "🌊 فيض رسائل",
                    f"5 رسائل في 5 ثوانٍ",
                    0xffaa00,
                    {"العضو": member.mention, "القناة": message.channel.mention},
                    member
                )
            except Exception as e:
                print(f"[Filter Error] flood: {e}")

# ==================== Slash Commands ====================
@bot.slash_command(name="تنبيه", description="إرسال تحذير رسمي لعضو")
async def warn_cmd(interaction: Interaction, member: nextcord.Member = SlashOption(description="العضو"), reason: str = SlashOption(description="السبب")):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ ليس لديك صلاحية", ephemeral=True)
        return
    if get_top_role_power(member) >= get_top_role_power(interaction.user):
        await interaction.response.send_message("❌ لا يمكنك تحذير عضو برتبة مساوية أو أعلى", ephemeral=True)
        return
    
    warn_counts[member.id] += 1
    count = warn_counts[member.id]
    
    emb = nextcord.Embed(title="⚠️ تحذير رسمي", description=f"تم تحذيرك من قبل {interaction.user.mention}", color=0xffaa00)
    emb.add_field(name="السبب", value=reason, inline=False)
    emb.add_field(name="عدد التحذيرات", value=str(count), inline=True)
    
    try:
        await member.send(embed=emb)
    except:
        pass
    
    await send_log(
        interaction.guild,
        "⚠️ تحذير",
        f"{member.mention} تلقى تحذيراً من {interaction.user.mention}",
        0xffaa00,
        {"السبب": reason, "العدد الإجمالي": str(count)},
        member
    )
    await interaction.response.send_message(f"✅ تم تحذير {member.mention} (العدد: {count})", ephemeral=True)

@bot.slash_command(name="تيم_أوت", description="وضع عضو في تيم أوت")
async def timeout_cmd(interaction: Interaction, member: nextcord.Member = SlashOption(description="العضو"), duration: int = SlashOption(description="المدة بالدقائق"), reason: str = SlashOption(description="السبب")):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ ليس لديك صلاحية", ephemeral=True)
        return
    if get_top_role_power(member) >= get_top_role_power(interaction.user):
        await interaction.response.send_message("❌ لا يمكنك عقاب عضو برتبة مساوية أو أعلى", ephemeral=True)
        return
    
    try:
        await member.timeout(timedelta(minutes=duration), reason=reason)
        await send_log(
            interaction.guild,
            "⏱️ Timeout",
            f"{member.mention} → تيم أوت",
            0xffa500,
            {"المدة": f"{duration} دقيقة", "السبب": reason, "بواسطة": interaction.user.mention},
            member
        )
        await interaction.response.send_message(f"✅ تم تيم أوت {member.mention} لمدة {duration} دقيقة", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

@bot.slash_command(name="ميوت", description="ميوت دائم باستخدام رتبة الميوت")
async def mute_cmd(interaction: Interaction, member: nextcord.Member = SlashOption(description="العضو"), reason: str = SlashOption(description="السبب")):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ ليس لديك صلاحية", ephemeral=True)
        return
    if get_top_role_power(member) >= get_top_role_power(interaction.user):
        await interaction.response.send_message("❌ لا يمكنك عقاب عضو برتبة مساوية أو أعلى", ephemeral=True)
        return
    
    mute_role = nextcord.utils.get(interaction.guild.roles, name="Muted") or nextcord.utils.get(interaction.guild.roles, name="ميوت")
    if not mute_role:
        await interaction.response.send_message("❌ لم يتم العثور على رتبة الميوت (اسمها يجب أن يكون 'Muted' أو 'ميوت')", ephemeral=True)
        return
    
    try:
        await member.add_roles(mute_role, reason=reason)
        muted_users.add(member.id)
        await send_log(
            interaction.guild,
            "🔇 Mute",
            f"{member.mention} تم ميوته",
            0x808080,
            {"السبب": reason, "بواسطة": interaction.user.mention},
            member
        )
        await interaction.response.send_message(f"✅ تم ميوت {member.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

@bot.slash_command(name="فك_الميوت", description="إزالة رتبة الميوت")
async def unmute_cmd(interaction: Interaction, member: nextcord.Member = SlashOption(description="العضو")):
    if not (is_supreme(interaction.user) or is_owner(interaction.user)):
        await interaction.response.send_message("❌ هذه الصلاحية محصورة بـ Supreme و Owner", ephemeral=True)
        return
    
    mute_role = nextcord.utils.get(interaction.guild.roles, name="Muted") or nextcord.utils.get(interaction.guild.roles, name="ميوت")
    if not mute_role:
        await interaction.response.send_message("❌ لم يتم العثور على رتبة الميوت", ephemeral=True)
        return
    
    try:
        await member.remove_roles(mute_role)
        muted_users.discard(member.id)
        await send_log(
            interaction.guild,
            "🔊 Unmute",
            f"{member.mention} تم فك ميوته",
            0x00ff00,
            {"بواسطة": interaction.user.mention},
            member
        )
        await interaction.response.send_message(f"✅ تم فك ميوت {member.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

@bot.slash_command(name="حظر", description="حظر عضو من السيرفر")
async def ban_cmd(interaction: Interaction, member: nextcord.Member = SlashOption(description="العضو"), reason: str = SlashOption(description="السبب")):
    if not (is_supreme(interaction.user) or is_owner(interaction.user)):
        await interaction.response.send_message("❌ هذه الصلاحية محصورة بـ Supreme و Owner", ephemeral=True)
        return
    if get_top_role_power(member) >= get_top_role_power(interaction.user):
        await interaction.response.send_message("❌ لا يمكنك حظر عضو برتبة مساوية أو أعلى", ephemeral=True)
        return
    
    try:
        await member.ban(reason=reason)
        await send_log(
            interaction.guild,
            "🚫 Ban",
            f"{member.mention} تم حظره",
            0xff0000,
            {"السبب": reason, "بواسطة": interaction.user.mention},
            member
        )
        await interaction.response.send_message(f"✅ تم حظر {member.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

@bot.slash_command(name="مسح", description="حذف عدد من الرسائل")
async def purge_cmd(interaction: Interaction, amount: int = SlashOption(description="عدد الرسائل (1-100)")):
    if not (is_supreme(interaction.user) or is_owner(interaction.user)):
        await interaction.response.send_message("❌ هذه الصلاحية محصورة بـ Supreme و Owner", ephemeral=True)
        return
    if amount < 1 or amount > 100:
        await interaction.response.send_message("❌ العدد يجب أن يكون بين 1 و 100", ephemeral=True)
        return
    
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await send_log(
            interaction.guild,
            "🧹 Purge",
            f"تم مسح {len(deleted)} رسالة من {interaction.channel.mention}",
            0x808080,
            {"بواسطة": interaction.user.mention}
        )
        await interaction.response.send_message(f"✅ تم مسح {len(deleted)} رسالة", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

@bot.slash_command(name="ضبط_القائمة", description="إضافة/حذف كلمات ممنوعة (Supreme فقط)")
async def config_words_cmd(interaction: Interaction, action: str = SlashOption(description="add أو remove"), word: str = SlashOption(description="الكلمة")):
    if not is_supreme(interaction.user):
        await interaction.response.send_message("❌ هذه الصلاحية محصورة بـ Supreme", ephemeral=True)
        return
    
    global BAD_WORDS
    action = action.lower().strip()
    word = word.lower().strip()
    
    if action == "add":
        BAD_WORDS.add(word)
        msg = f"✅ تم إضافة `{word}`"
    elif action == "remove":
        BAD_WORDS.discard(word)
        msg = f"✅ تم حذف `{word}`"
    else:
        await interaction.response.send_message("❌ الإجراء يجب أن يكون add أو remove", ephemeral=True)
        return
    
    with open("badwords.json", "w", encoding="utf-8") as f:
        json.dump(list(BAD_WORDS), f, ensure_ascii=False, indent=2)
    
    await interaction.response.send_message(msg, ephemeral=True)

@bot.slash_command(name="حالة_البوت", description="عرض إحصائيات البوت")
async def stats_cmd(interaction: Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ ليس لديك صلاحية", ephemeral=True)
        return
    
    emb = nextcord.Embed(title="🛡️ DeepGuard Stats", color=0x00ffcc)
    emb.add_field(name="التحذيرات النشطة", value=str(len(warn_counts)), inline=True)
    emb.add_field(name="الميوت النشط", value=str(len(muted_users)), inline=True)
    emb.add_field(name="الكاش (رسائل)", value=str(sum(len(v) for v in message_cache.values())), inline=True)
    emb.add_field(name="السيرفرات", value=str(len(bot.guilds)), inline=True)
    await interaction.response.send_message(embed=emb, ephemeral=True)

# ==================== التشغيل ====================
if __name__ == "__main__":
    bot.run(TOKEN)
