import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from utils.helpers import admin_only


class CheckinDebug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='測試簽到', description='診斷簽到系統目前狀態（僅限管理員）')
    @admin_only()
    async def slash_checkin_debug(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        settings     = db.get_channel_settings(guild_id, channel_id)
        reset_hour   = settings.get('reset_hour', 0)
        reset_minute = settings.get('reset_minute', 0)
        tz_name      = db.get_timezone(guild_id)
        now          = db.get_now(guild_id)

        today_str        = db.get_today_str(guild_id, reset_hour, reset_minute)
        announce_date    = (
            datetime.strptime(today_str, '%Y-%m-%d') - timedelta(days=1)
        ).strftime('%Y-%m-%d')

        today_checkins   = db.get_today_checkins(guild_id, channel_id, today_str)
        user_checked_in  = str(interaction.user.id) in today_checkins
        user_data        = db.get_user_checkin(guild_id, interaction.user.id)

        # 距離下次重置
        now_total   = now.hour * 60 + now.minute
        reset_total = reset_hour * 60 + reset_minute
        diff_min    = (reset_total - now_total) % 1440
        hours_left  = diff_min // 60
        mins_left   = diff_min % 60

        embed = discord.Embed(
            title='🔧 簽到系統診斷',
            color=0xE67E22
        )
        embed.add_field(
            name='⏰ 目前時間',
            value=f'`{now.strftime("%Y-%m-%d %H:%M:%S")}`\n時區：{tz_name}',
            inline=False
        )
        embed.add_field(
            name='🔄 重置設定',
            value=(
                f'重置時間：`{reset_hour:02d}:{reset_minute:02d}`\n'
                f'距離下次重置：**{hours_left}** 小時 **{mins_left}** 分鐘'
            ),
            inline=False
        )
        embed.add_field(
            name='📅 簽到日期判斷',
            value=(
                f'今日簽到用日期：`{today_str}`\n'
                f'每日統計公告日期：`{announce_date}`'
            ),
            inline=False
        )
        embed.add_field(
            name=f'👤 你的簽到狀態',
            value=(
                f'今日已簽到：{"✅ 是" if user_checked_in else "❌ 尚未"}\n'
                f'總簽到次數：**{user_data.get("total", 0) if user_data else 0}** 次\n'
                f'連續簽到：**{user_data.get("streak", 0) if user_data else 0}** 天\n'
                f'上次簽到：`{user_data.get("last_checkin", "無") if user_data else "無"}`'
            ),
            inline=False
        )
        embed.add_field(
            name=f'📊 本頻道今日簽到人數',
            value=f'**{len(today_checkins)}** 人',
            inline=False
        )
        embed.set_footer(text=f'頻道：#{interaction.channel.name}')

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CheckinDebug(bot))
