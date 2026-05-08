import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from utils.helpers import admin_only


def _streak_emoji(streak: int) -> str:
    if streak >= 30: return '🏆'
    if streak >= 14: return '🔥'
    if streak >= 7:  return '⚡'
    if streak >= 3:  return '✨'
    return ''


def _build_leaderboard_embed(title, color, entries):
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
    return embed


class CheckInView(discord.ui.View):
    """持久化按鈕面板（timeout=None，重啟後仍可使用）。"""

    def __init__(self):
        super().__init__(timeout=None)

    # ── ✅ 簽到 ──────────────────────────────────────────────────
    @discord.ui.button(
        label='簽到', style=discord.ButtonStyle.success,
        emoji='✅', custom_id='panel_checkin'
    )
    async def btn_checkin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        db         = interaction.client.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        user       = interaction.user

        if not db.is_checkin_channel(guild_id, channel_id):
            allowed = db.get_checkin_channels(guild_id)
            mentions = [
                interaction.guild.get_channel(int(cid)).mention
                for cid in allowed if interaction.guild.get_channel(int(cid))
            ]
            await interaction.followup.send(
                f'❌ 此頻道不開放簽到！請前往：{"、".join(mentions) or "（無設定）"}',
                ephemeral=True
            )
            return

        if db.is_blacklisted(guild_id, channel_id, user.id):
            await interaction.followup.send('❌ 你已被加入黑名單，無法在此頻道簽到。', ephemeral=True)
            return

        settings      = db.get_channel_settings(guild_id, channel_id)
        reset_hour    = settings.get('reset_hour', 23)
        reset_minute  = settings.get('reset_minute', 59)
        require_proof = settings.get('require_proof', False)
        min_words     = settings.get('min_words', 0)

        if require_proof:
            await interaction.followup.send(
                '❌ 此頻道需要附截圖！請在頻道傳送圖片後改用 `/簽到`。',
                ephemeral=True
            )
            return
        if min_words > 0:
            await interaction.followup.send(
                f'❌ 此頻道需要至少 **{min_words}** 個字的簽到訊息！請改用 `/簽到 訊息:你的留言`。',
                ephemeral=True
            )
            return

        today_str = db.get_today_str(guild_id, reset_hour, reset_minute)

        nickname = db.get_nickname(guild_id, user.id)
        display_name = nickname if nickname else (user.display_name or user.name)
        user_data = db.get_user_checkin(guild_id, user.id)
        if not user_data:
            user_data = db.init_user(guild_id, user.id, display_name)
        elif not nickname:
            user_data['display_name'] = display_name

        if str(user.id) in db.get_today_checkins(guild_id, channel_id, today_str):
            await interaction.followup.send('⚠️ 你今天已經簽到過了！', ephemeral=True)
            return

        last_checkin = user_data.get('last_checkin')
        if last_checkin:
            diff = (
                datetime.strptime(today_str, '%Y-%m-%d').date() -
                datetime.strptime(last_checkin, '%Y-%m-%d').date()
            ).days
            user_data['streak'] = (user_data.get('streak', 0) + 1) if diff == 1 else 1
        else:
            user_data['streak'] = 1

        user_data['max_streak'] = max(user_data.get('max_streak', 0), user_data['streak'])
        user_data['total']       = user_data.get('total', 0) + 1
        user_data['last_checkin'] = today_str
        user_data.setdefault('history', []).append(today_str)
        user_data['display_name'] = display_name

        db.save_user_checkin(guild_id, user.id, user_data)
        db.add_today_checkin(guild_id, channel_id, user.id, today_str)

        streak = user_data['streak']
        total  = user_data['total']

        embed = discord.Embed(title='✅ 簽到成功！', color=0x57F287)
        embed.set_author(name=display_name, icon_url=user.display_avatar.url)
        embed.description = (
            f'📅 日期：**{today_str}**\n'
            f'📊 總簽到：**{total}** 次\n'
            f'{_streak_emoji(streak)} 連續簽到：**{streak}** 天'
        )
        if streak >= 3:
            embed.set_footer(text=f'🎯 連續 {streak} 天，繼續加油！')

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 📊 簽到排行 ──────────────────────────────────────────────
    @discord.ui.button(
        label='簽到排行', style=discord.ButtonStyle.primary,
        emoji='📊', custom_id='panel_leaderboard'
    )
    async def btn_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        db         = interaction.client.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        active = {uid: d for uid, d in all_users.items()
                  if not db.is_blacklisted(guild_id, channel_id, uid)}
        sorted_users = sorted(active.items(), key=lambda x: x[1].get('total', 0), reverse=True)
        entries = [
            (db.get_display_name(guild_id, uid), f"**{d.get('total', 0)}** 次")
            for uid, d in sorted_users[:50]
        ]
        embed = _build_leaderboard_embed('📊 簽到排行榜（前 50 名）', 0x57F287, entries)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 🔥 連續簽到排行 ──────────────────────────────────────────
    @discord.ui.button(
        label='連續簽到排行', style=discord.ButtonStyle.primary,
        emoji='🔥', custom_id='panel_streak'
    )
    async def btn_streak(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        db         = interaction.client.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        all_users  = db.get_all_checkins(guild_id)

        active = {uid: d for uid, d in all_users.items()
                  if not db.is_blacklisted(guild_id, channel_id, uid)}
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
        embed = _build_leaderboard_embed('🔥 連續簽到排行榜（前 50 名）', 0xF1C40F, entries)
        await interaction.followup.send(embed=embed, ephemeral=True)


class Panel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='簽到面板', description='在此頻道發布簽到控制台面板（僅限管理員）')
    @admin_only()
    async def slash_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='📋 簽到控制台',
            description=(
                '歡迎使用簽到系統！點擊下方按鈕進行操作：\n\n'
                '✅ **簽到** — 每日簽到\n'
                '📊 **簽到排行** — 查看總簽到次數排行\n'
                '🔥 **連續簽到排行** — 查看連續簽到天數排行\n\n'
                '> 所有回應只有你自己看得到'
            ),
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed, view=CheckInView())


async def setup(bot):
    await bot.add_cog(Panel(bot))
