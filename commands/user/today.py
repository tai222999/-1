import discord
from discord import app_commands
from discord.ext import commands


class Today(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='今日簽到', description='查看今天這個頻道已簽到的成員（只有你看得到）')
    async def slash_today(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        settings     = db.get_channel_settings(guild_id, channel_id)
        reset_hour   = settings.get('reset_hour', 23)
        reset_minute = settings.get('reset_minute', 59)
        today_str    = db.get_today_str(guild_id, reset_hour, reset_minute)
        tz_name      = db.get_timezone(guild_id)

        today_user_ids = db.get_today_checkins(guild_id, channel_id, today_str)

        embed = discord.Embed(
            title=f'📅 今日簽到名單 — {today_str}',
            color=0x5865F2
        )

        if not today_user_ids:
            embed.description = '今天還沒有人簽到！\n點擊面板按鈕或使用 `/簽到` 來第一個簽到吧 🎯'
        else:
            lines = [
                f'`{i:>2}.` {db.get_display_name(guild_id, uid, fallback=f"使用者 {uid}")}'
                for i, uid in enumerate(today_user_ids, 1)
            ]
            embed.description = '\n'.join(lines)

        embed.set_footer(
            text=f'共 {len(today_user_ids)} 人簽到 ｜ 時區：{tz_name} ｜ 重置：{reset_hour:02d}:{reset_minute:02d}'
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Today(bot))
