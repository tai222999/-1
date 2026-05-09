import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import LeaderboardView, LB_PAGE_SIZE


async def _send_lb(interaction: discord.Interaction,
                   entries: list, title: str, color: int):
    """以分頁排行榜回應（ephemeral followup）。"""
    view  = LeaderboardView(entries, title, color, interaction.user.id)
    embed = view.build_embed()
    if view.total_pages > 1:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, ephemeral=True)


class Leaderboards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /簽到排行 ────────────────────────────────────────────────
    @app_commands.command(name='簽到排行', description='查看簽到次數排行榜（只有你看得到）')
    async def slash_win_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        active = {
            uid: d for uid, d in all_users.items()
            if not db.is_blacklisted(guild_id, channel_id, uid)
        }
        sorted_users = sorted(active.items(), key=lambda x: x[1].get('total', 0), reverse=True)
        entries = [
            (db.get_display_name(guild_id, uid), f"**{d.get('total', 0)}** 次")
            for uid, d in sorted_users
        ]
        await _send_lb(interaction, entries, '📊 簽到排行榜', 0x57F287)

    # ── /連續簽到排行 ────────────────────────────────────────────
    @app_commands.command(name='連續簽到排行', description='查看連續簽到天數排行榜（只有你看得到）')
    async def slash_streak_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        active = {
            uid: d for uid, d in all_users.items()
            if not db.is_blacklisted(guild_id, channel_id, uid)
        }
        sorted_users = sorted(
            active.items(),
            key=lambda x: (x[1].get('streak', 0), x[1].get('max_streak', 0)),
            reverse=True,
        )
        entries = [
            (
                db.get_display_name(guild_id, uid),
                f"連續 **{d.get('streak', 0)}** 天（最高 {d.get('max_streak', 0)} 天）",
            )
            for uid, d in sorted_users
        ]
        await _send_lb(interaction, entries, '🔥 連續簽到排行榜', 0xF1C40F)

    # ── /未簽到排行 ──────────────────────────────────────────────
    @app_commands.command(name='未簽到排行', description='查看未簽到次數排行榜（只有你看得到）')
    async def slash_lose_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        active = {
            uid: d for uid, d in all_users.items()
            if not db.is_blacklisted(guild_id, channel_id, uid)
        }
        sorted_users = sorted(active.items(), key=lambda x: x[1].get('miss', 0), reverse=True)
        entries = [
            (db.get_display_name(guild_id, uid), f"缺席 **{d.get('miss', 0)}** 次")
            for uid, d in sorted_users
        ]
        await _send_lb(interaction, entries, '❌ 未簽到排行榜', 0xED4245)

    # ── /連續簽到超過7天 ─────────────────────────────────────────
    @app_commands.command(name='連續簽到超過7天', description='列出目前連續簽到達 7 天以上的成員（只有你看得到）')
    async def slash_streak_7(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        qualified = [
            (uid, d) for uid, d in all_users.items()
            if d.get('streak', 0) >= 7
            and not db.is_blacklisted(guild_id, channel_id, uid)
        ]
        qualified.sort(key=lambda x: x[1].get('streak', 0), reverse=True)

        def _emoji(s):
            return '🏆' if s >= 30 else '🔥' if s >= 14 else '⚡'

        entries = [
            (
                db.get_display_name(guild_id, uid),
                f'{_emoji(d.get("streak", 0))} 連續 **{d.get("streak", 0)}** 天（最高 {d.get("max_streak", 0)} 天）',
            )
            for uid, d in qualified
        ]
        await _send_lb(interaction, entries, '⚡ 連續簽到 7 天以上', 0xF1C40F)

    # ── /連續簽到超過26天 ────────────────────────────────────────
    @app_commands.command(name='連續簽到超過26天', description='列出目前連續簽到達 26 天以上的成員（只有你看得到）')
    async def slash_streak_26(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        qualified = [
            (uid, d) for uid, d in all_users.items()
            if d.get('streak', 0) >= 26
            and not db.is_blacklisted(guild_id, channel_id, uid)
        ]
        qualified.sort(key=lambda x: x[1].get('streak', 0), reverse=True)

        entries = [
            (
                db.get_display_name(guild_id, uid),
                f'🏆 連續 **{d.get("streak", 0)}** 天（最高 {d.get("max_streak", 0)} 天）',
            )
            for uid, d in qualified
        ]
        await _send_lb(interaction, entries, '🏆 連續簽到 26 天以上', 0xFFD700)


async def setup(bot):
    await bot.add_cog(Leaderboards(bot))
