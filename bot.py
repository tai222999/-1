import discord
from discord.ext import commands
from discord import app_commands
import os
from utils.database import Database
from utils.config import Config
from dotenv import load_dotenv
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='_disabled_', intents=intents, help_command=None)
db = Database()
config = Config()

bot.db = db
bot.config = config

TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise RuntimeError('環境變數 DISCORD_TOKEN 未設定！')

async def load_extensions():
    extensions = [
        'commands.user.manual',
        'commands.user.checkin',
        'commands.user.today',
        'commands.user.leaderboards',
        'commands.user.reset_info',
        'commands.user.panel',
        'commands.admin.nickname',
        'commands.admin.adjust',
        'commands.admin.settings',
        'commands.admin.blacklist',
        'commands.admin.admin_manage',
        'commands.admin.leaderboard_reset',
        'commands.admin.scheduler',
        'commands.admin.set_channel',
        'commands.admin.init_setup',
        'commands.admin.maple_news',
        'commands.user.lottery',
        'commands.user.raid',
        'commands.user.donation',
        'commands.admin.announcement',
        'commands.user.party',
        'commands.user.drops',
        'commands.user.checkin_lottery',
        'commands.user.general_lottery',
        'commands.user.leave',
        'commands.admin.welcome',
        'commands.admin.role_panel',
        'commands.admin.voice_channel',
        'commands.admin.checkin_debug',
    ]
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f'✅ 載入：{ext}')
        except Exception as e:
            print(f'❌ 載入失敗：{ext}\n   {type(e).__name__}: {e}')

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = ''
    if isinstance(error, app_commands.CheckFailure):
        msg = '❌ 此指令僅限管理員使用。'
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f'❌ 指令冷卻中，請稍後再試。'
    else:
        msg = f'❌ 發生錯誤：{str(error)}'
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

@bot.event
async def on_ready():
    from commands.user.panel import CheckInView
    bot.add_view(CheckInView())

    # 修正舊版 23:59 預設值
    db.migrate_reset_times()

    # 只做伺服器層級同步（立刻生效，避免與全域指令重複）
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f'🔄 已同步伺服器：{guild.name}（{len(synced)} 個指令）')
        except Exception as e:
            print(f'⚠️ 同步伺服器 {guild.name} 失敗：{e}')

    print(f'✅ {bot.user} 已上線！')
    print(f'📋 Bot ID: {bot.user.id}')

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
