import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /設定重置時間 ────────────────────────────────────────────
    @app_commands.command(name='設定重置時間', description='設定此頻道的每日簽到重置時間（預設 00:00 午夜）')
    @app_commands.describe(時間='格式 HH:MM，例如 00:00 或 04:00（幾點後算隔天）')
    @admin_only()
    async def slash_set_reset(self, interaction: discord.Interaction, 時間: str = '00:00'):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        try:
            parts  = 時間.split(':')
            hour   = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, IndexError):
            await interaction.response.send_message(
                '❌ 格式錯誤，請輸入 `HH:MM`，例如：`23:59`', ephemeral=True
            )
            return

        settings = db.get_channel_settings(guild_id, channel_id)
        settings['reset_hour']   = hour
        settings['reset_minute'] = minute
        db.save_channel_settings(guild_id, channel_id, settings)

        await interaction.response.send_message(
            f'✅ **#{interaction.channel.name}** 的簽到重置時間已設定為 **{hour:02d}:{minute:02d}**'
            f'（時區：{db.get_timezone(guild_id)}）',
            ephemeral=True
        )

    # ── /切換截圖要求 ────────────────────────────────────────────
    @app_commands.command(name='切換截圖要求', description='開關此頻道的截圖證明要求')
    @admin_only()
    async def slash_toggle_proof(self, interaction: discord.Interaction):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        settings = db.get_channel_settings(guild_id, channel_id)
        settings['require_proof'] = not settings.get('require_proof', False)
        db.save_channel_settings(guild_id, channel_id, settings)

        status = '**需要**截圖證明' if settings['require_proof'] else '**不需要**截圖證明'
        await interaction.response.send_message(
            f'✅ **#{interaction.channel.name}** 的簽到現在{status}。', ephemeral=True
        )

    # ── /設定最少字數 ────────────────────────────────────────────
    @app_commands.command(name='設定最少字數', description='設定簽到訊息的最少字數（0 為不限制）')
    @app_commands.describe(字數='最少字數，0 代表不限制')
    @admin_only()
    async def slash_set_min_words(self, interaction: discord.Interaction, 字數: int):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        if 字數 < 0:
            await interaction.response.send_message('❌ 字數不能為負數，輸入 0 代表不限制。', ephemeral=True)
            return

        settings = db.get_channel_settings(guild_id, channel_id)
        settings['min_words'] = 字數
        db.save_channel_settings(guild_id, channel_id, settings)

        if 字數 == 0:
            await interaction.response.send_message(
                f'✅ **#{interaction.channel.name}** 的簽到訊息字數限制已移除。', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f'✅ **#{interaction.channel.name}** 的簽到訊息最少需要 **{字數}** 個字。', ephemeral=True
            )

    # ── /切換每日公告 ────────────────────────────────────────────
    @app_commands.command(name='切換每日公告', description='開關此頻道的每日簽到統計公告')
    @admin_only()
    async def slash_toggle_daily(self, interaction: discord.Interaction):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        settings = db.get_channel_settings(guild_id, channel_id)
        settings['announce_enabled'] = not settings.get('announce_enabled', True)
        db.save_channel_settings(guild_id, channel_id, settings)

        status = '**已開啟**' if settings['announce_enabled'] else '**已關閉**'
        extra = (
            '每到重置時間，Bot 會在此頻道發送當日簽到統計。'
            if settings['announce_enabled'] else
            '此頻道將不再自動發送每日統計公告。'
        )
        await interaction.response.send_message(
            f'✅ **#{interaction.channel.name}** 的每日簽到統計公告{status}。\n{extra}',
            ephemeral=True
        )

    # ── /設定時區 ────────────────────────────────────────────────
    @app_commands.command(name='設定時區', description='查看或設定伺服器時區（留空則列出所有可用時區）')
    @app_commands.describe(時區='時區名稱，例如 Asia/Taipei（留空則列出全部）')
    @admin_only()
    async def slash_set_timezone(self, interaction: discord.Interaction, 時區: str = ''):
        db     = self.bot.db
        config = self.bot.config
        guild_id = interaction.guild_id

        if not 時區:
            zones   = config.get_all_timezones()
            current = db.get_timezone(guild_id)
            embed = discord.Embed(
                title='🌏 可用時區列表',
                description='\n'.join(f'`{z}`' for z in zones),
                color=0x5865F2
            )
            embed.set_footer(text=f'目前時區：{current} ｜ 使用 /設定時區 時區:Asia/Taipei 來設定')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not config.is_valid_timezone(時區):
            await interaction.response.send_message(
                f'❌ 無效的時區：`{時區}`，請使用 `/設定時區` 查看可用時區。', ephemeral=True
            )
            return

        gs = db.get_guild_settings(guild_id)
        gs['timezone'] = 時區
        db.save_guild_settings(guild_id, gs)
        await interaction.response.send_message(f'✅ 伺服器時區已設定為：**{時區}**', ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))
