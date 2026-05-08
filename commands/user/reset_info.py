import discord
from discord import app_commands
from discord.ext import commands


class ResetInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='重置資訊', description='查看此頻道的簽到重置時間與伺服器時區（只有你看得到）')
    async def slash_reset_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        settings     = db.get_channel_settings(guild_id, channel_id)
        reset_hour   = settings.get('reset_hour', 23)
        reset_minute = settings.get('reset_minute', 59)
        announce_on  = settings.get('announce_enabled', True)
        tz_name      = db.get_timezone(guild_id)
        now          = db.get_now(guild_id)

        now_total   = now.hour * 60 + now.minute
        reset_total = reset_hour * 60 + reset_minute
        diff_min    = (reset_total - now_total) % 1440
        hours_left  = diff_min // 60
        mins_left   = diff_min % 60

        embed = discord.Embed(title='⏰ 簽到重置設定', color=0x5865F2)
        embed.add_field(name='🌏 伺服器時區',   value=tz_name,                                 inline=True)
        embed.add_field(name='🔄 每日重置時間', value=f'{reset_hour:02d}:{reset_minute:02d}', inline=True)
        embed.add_field(name='🕐 目前時間',     value=now.strftime('%Y-%m-%d %H:%M'),          inline=True)
        embed.add_field(
            name='⏳ 距離下次重置',
            value=f'約 **{hours_left}** 小時 **{mins_left}** 分鐘',
            inline=False
        )
        embed.add_field(
            name='📢 每日統計公告',
            value=f'{"✅ 開啟" if announce_on else "❌ 關閉"} ｜ 時間：{reset_hour:02d}:{reset_minute:02d}',
            inline=False
        )
        embed.set_footer(text=f'頻道：#{interaction.channel.name}')
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ResetInfo(bot))
