import discord
from discord import app_commands
from discord.ext import commands


def _build_embed(title, color, entries, footer=''):
    embed = discord.Embed(title=title, color=color)
    if not entries:
        embed.description = '目前沒有任何資料。'
    else:
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}
        lines = [
            f"{medals.get(i, f'`{i:>2}.`')} **{name}** — {value}"
            for i, (name, value) in enumerate(entries, 1)
        ]
        embed.description = '\n'.join(lines)
    if footer:
        embed.set_footer(text=footer)
    return embed


class Leaderboards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /簽到排行 ────────────────────────────────────────────────
    @app_commands.command(name='簽到排行', description='查看簽到次數排行榜（前 50 名，只有你看得到）')
    async def slash_win_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
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
            for uid, d in sorted_users[:50]
        ]
        embed = _build_embed('📊 簽到排行榜（前 50 名）', 0x57F287, entries)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /連續簽到排行 ────────────────────────────────────────────
    @app_commands.command(name='連續簽到排行', description='查看連續簽到天數排行榜（前 50 名，只有你看得到）')
    async def slash_streak_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
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
            reverse=True
        )
        entries = [
            (
                db.get_display_name(guild_id, uid),
                f"連續 **{d.get('streak', 0)}** 天（最高 {d.get('max_streak', 0)} 天）"
            )
            for uid, d in sorted_users[:50]
        ]
        embed = _build_embed('🔥 連續簽到排行榜（前 50 名）', 0xF1C40F, entries)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /未簽到排行 ──────────────────────────────────────────────
    @app_commands.command(name='未簽到排行', description='查看未簽到次數排行榜（前 50 名，只有你看得到）')
    async def slash_lose_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
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
            for uid, d in sorted_users[:50]
        ]
        embed = _build_embed('❌ 未簽到排行榜（前 50 名）', 0xED4245, entries)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /連續簽到超過7天 ─────────────────────────────────────────
    @app_commands.command(name='連續簽到超過7天', description='列出目前連續簽到達 7 天以上的成員（只有你看得到）')
    async def slash_streak_7(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        qualified = [
            (uid, d) for uid, d in all_users.items()
            if d.get('streak', 0) >= 7
            and not db.is_blacklisted(guild_id, channel_id, uid)
        ]
        qualified.sort(key=lambda x: x[1].get('streak', 0), reverse=True)

        embed = discord.Embed(title='⚡ 連續簽到 7 天以上', color=0xF1C40F)
        if not qualified:
            embed.description = '目前沒有任何成員連續簽到達 7 天以上。'
        else:
            medals = {1: '🥇', 2: '🥈', 3: '🥉'}
            lines = []
            for i, (uid, d) in enumerate(qualified, 1):
                name   = db.get_display_name(guild_id, uid)
                streak = d.get('streak', 0)
                best   = d.get('max_streak', 0)
                emoji  = '🏆' if streak >= 30 else '🔥' if streak >= 14 else '⚡'
                prefix = medals.get(i, f'`{i:>2}.`')
                lines.append(f'{prefix} {emoji} **{name}** — 連續 **{streak}** 天（最高 {best} 天）')
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'共 {len(qualified)} 位成員達標')

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /連續簽到超過26天 ────────────────────────────────────────
    @app_commands.command(name='連續簽到超過26天', description='列出目前連續簽到達 26 天以上的成員（只有你看得到）')
    async def slash_streak_26(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        qualified = [
            (uid, d) for uid, d in all_users.items()
            if d.get('streak', 0) >= 26
            and not db.is_blacklisted(guild_id, channel_id, uid)
        ]
        qualified.sort(key=lambda x: x[1].get('streak', 0), reverse=True)

        embed = discord.Embed(title='🏆 連續簽到 26 天以上', color=0xFFD700)
        if not qualified:
            embed.description = '目前沒有任何成員連續簽到達 26 天以上。'
        else:
            medals = {1: '🥇', 2: '🥈', 3: '🥉'}
            lines = []
            for i, (uid, d) in enumerate(qualified, 1):
                name   = db.get_display_name(guild_id, uid)
                streak = d.get('streak', 0)
                best   = d.get('max_streak', 0)
                prefix = medals.get(i, f'`{i:>2}.`')
                lines.append(f'{prefix} 🏆 **{name}** — 連續 **{streak}** 天（最高 {best} 天）')
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'共 {len(qualified)} 位成員達標 | 恭喜這些強者！')

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Leaderboards(bot))
