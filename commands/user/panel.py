import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime
from utils.helpers import admin_only

PANEL_DESC = (
    '歡迎使用簽到系統！點擊下方按鈕進行操作：\n\n'
    '✅ **簽到** — 每日簽到（獲得 1 枚簽到幣）\n'
    '📊 **簽到排行** — 查看總簽到次數排行\n'
    '🔥 **連續簽到排行** — 查看連續簽到天數排行\n'
    '💰 **查詢簽到幣** — 查看目前擁有的簽到幣\n'
    '🎫 **查詢抽獎卷** — 查看周抽及月抽獎卷數量\n'
    '🔄 **兌換抽獎卷** — 用簽到幣兌換抽獎卷\n\n'
    '> 所有回應只有你自己看得到'
)


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


# ── 兌換視圖（ephemeral，非持久化）────────────────────────────────

class ExchangeView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @ui.button(label='🗓️ 兌換周抽獎卷（7幣 = 1張）', style=discord.ButtonStyle.success, row=0)
    async def exchange_weekly(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        success, wallet = db.exchange_tickets(interaction.guild_id, interaction.user.id, 'weekly', 7)
        if not success:
            await interaction.response.send_message(
                f'❌ 簽到幣不足！需要 **7** 枚，你目前有 **{wallet.get("coins", 0)}** 枚。',
                ephemeral=True)
            return
        await interaction.response.send_message(
            f'✅ 兌換成功！獲得 **1 張周抽獎卷**\n'
            f'💰 剩餘簽到幣：**{wallet["coins"]}** 枚\n'
            f'🗓️ 周抽獎卷：**{wallet.get("weekly_tickets", 0)}** 張',
            ephemeral=True)

    @ui.button(label='📅 兌換月抽獎卷（26幣 = 1張）', style=discord.ButtonStyle.primary, row=0)
    async def exchange_monthly(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        success, wallet = db.exchange_tickets(interaction.guild_id, interaction.user.id, 'monthly', 26)
        if not success:
            await interaction.response.send_message(
                f'❌ 簽到幣不足！需要 **26** 枚，你目前有 **{wallet.get("coins", 0)}** 枚。',
                ephemeral=True)
            return
        await interaction.response.send_message(
            f'✅ 兌換成功！獲得 **1 張月抽獎卷**\n'
            f'💰 剩餘簽到幣：**{wallet["coins"]}** 枚\n'
            f'📅 月抽獎卷：**{wallet.get("monthly_tickets", 0)}** 張',
            ephemeral=True)


# ── 簽到面板（持久化）────────────────────────────────────────────

class CheckInView(discord.ui.View):
    """持久化按鈕面板（timeout=None，重啟後仍可使用）。"""

    def __init__(self):
        super().__init__(timeout=None)

    # ── ✅ 簽到 ──────────────────────────────────────────────────
    @discord.ui.button(
        label='簽到', style=discord.ButtonStyle.success,
        emoji='✅', custom_id='panel_checkin', row=0
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
                ephemeral=True)
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
                '❌ 此頻道需要附截圖！請在頻道傳送圖片後改用 `/簽到`。', ephemeral=True)
            return
        if min_words > 0:
            await interaction.followup.send(
                f'❌ 此頻道需要至少 **{min_words}** 個字的簽到訊息！請改用 `/簽到 訊息:你的留言`。',
                ephemeral=True)
            return

        today_str = db.get_today_str(guild_id, reset_hour, reset_minute)

        nickname     = db.get_nickname(guild_id, user.id)
        display_name = nickname if nickname else (user.display_name or user.name)
        user_data    = db.get_user_checkin(guild_id, user.id)
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

        user_data['max_streak']   = max(user_data.get('max_streak', 0), user_data['streak'])
        user_data['total']        = user_data.get('total', 0) + 1
        user_data['last_checkin'] = today_str
        user_data.setdefault('history', []).append(today_str)
        user_data['display_name'] = display_name

        db.save_user_checkin(guild_id, user.id, user_data)
        db.add_today_checkin(guild_id, channel_id, user.id, today_str)

        # 發放簽到幣
        new_coins = db.add_coins(guild_id, user.id, 1)

        streak = user_data['streak']
        total  = user_data['total']

        embed = discord.Embed(title='✅ 簽到成功！', color=0x57F287)
        embed.set_author(name=display_name, icon_url=user.display_avatar.url)
        embed.description = (
            f'📅 日期：**{today_str}**\n'
            f'📊 總簽到：**{total}** 次\n'
            f'{_streak_emoji(streak)} 連續簽到：**{streak}** 天\n'
            f'💰 獲得 1 枚簽到幣（共 **{new_coins}** 枚）'
        )
        if streak >= 3:
            embed.set_footer(text=f'🎯 連續 {streak} 天，繼續加油！')

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 📊 簽到排行 ──────────────────────────────────────────────
    @discord.ui.button(
        label='簽到排行', style=discord.ButtonStyle.primary,
        emoji='📊', custom_id='panel_leaderboard', row=0
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
        emoji='🔥', custom_id='panel_streak', row=0
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
            reverse=True,
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

    # ── 💰 查詢簽到幣 ────────────────────────────────────────────
    @discord.ui.button(
        label='查詢簽到幣', style=discord.ButtonStyle.secondary,
        emoji='💰', custom_id='panel_coins', row=1
    )
    async def btn_coins(self, interaction: discord.Interaction, button: discord.ui.Button):
        db     = interaction.client.db
        wallet = db.get_user_wallet(interaction.guild_id, interaction.user.id)
        coins  = wallet.get('coins', 0)
        embed  = discord.Embed(title='💰 簽到幣餘額', color=0xF1C40F)
        embed.description = (
            f'你目前擁有 **{coins}** 枚簽到幣\n\n'
            f'💡 每日簽到可獲得 **1** 枚\n'
            f'🔄 兌換比例：\n'
            f'　🗓️ 周抽獎卷 = **7** 枚\n'
            f'　📅 月抽獎卷 = **26** 枚'
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 🎫 查詢抽獎卷 ────────────────────────────────────────────
    @discord.ui.button(
        label='查詢抽獎卷', style=discord.ButtonStyle.secondary,
        emoji='🎫', custom_id='panel_tickets', row=1
    )
    async def btn_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        db     = interaction.client.db
        wallet = db.get_user_wallet(interaction.guild_id, interaction.user.id)
        weekly  = wallet.get('weekly_tickets', 0)
        monthly = wallet.get('monthly_tickets', 0)
        embed   = discord.Embed(title='🎫 抽獎卷餘額', color=0x9B59B6)
        embed.description = (
            f'🗓️ **周抽獎卷**：**{weekly}** 張\n'
            f'　（兌換需 7 枚簽到幣）\n\n'
            f'📅 **月抽獎卷**：**{monthly}** 張\n'
            f'　（兌換需 26 枚簽到幣）'
        )
        embed.set_footer(text='點擊「兌換抽獎卷」按鈕可以進行兌換')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 🔄 兌換抽獎卷 ────────────────────────────────────────────
    @discord.ui.button(
        label='兌換抽獎卷', style=discord.ButtonStyle.success,
        emoji='🔄', custom_id='panel_exchange', row=1
    )
    async def btn_exchange(self, interaction: discord.Interaction, button: discord.ui.Button):
        db     = interaction.client.db
        wallet = db.get_user_wallet(interaction.guild_id, interaction.user.id)
        coins  = wallet.get('coins', 0)
        embed  = discord.Embed(title='🔄 兌換抽獎卷', color=0x2ECC71)
        embed.description = (
            f'💰 你目前有 **{coins}** 枚簽到幣\n\n'
            '選擇要兌換的類型：\n'
            '🗓️ **周抽獎卷** — 7 枚簽到幣兌換 1 張\n'
            '📅 **月抽獎卷** — 26 枚簽到幣兌換 1 張'
        )
        await interaction.response.send_message(embed=embed, view=ExchangeView(), ephemeral=True)


class Panel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='簽到面板', description='在此頻道發布簽到控制台面板（僅限管理員）')
    @admin_only()
    async def slash_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='📋 簽到控制台',
            description=PANEL_DESC,
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, view=CheckInView())


async def setup(bot):
    await bot.add_cog(Panel(bot))
