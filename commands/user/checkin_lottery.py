import discord
from discord import app_commands, ui
from discord.ext import commands
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils.database import _load, _save
from utils.helpers import admin_only

TW_TZ = timezone(timedelta(hours=8))
LOTTERY_FILE = 'checkin_lotteries.json'

active_lotteries: dict = {}   # {guild_id_str: {msg_id_str: {...}}}

TYPE_LABEL   = {'weekly': '周抽', 'monthly': '月抽'}
TYPE_COLOR   = {'weekly': 0xF1C40F, 'monthly': 0x9B59B6}
TICKET_KEY   = {'weekly': 'weekly_tickets', 'monthly': 'monthly_tickets'}
TICKET_LABEL = {'weekly': '周抽獎卷', 'monthly': '月抽獎卷'}


def tw_now() -> datetime:
    return datetime.now(TW_TZ)


# ── 資料存取 ──────────────────────────────────────────────────────

def _load_lotteries():
    global active_lotteries
    raw = _load(LOTTERY_FILE)
    active_lotteries = raw if isinstance(raw, dict) else {}

def _save_lotteries():
    _save(LOTTERY_FILE, active_lotteries)


# ── Embed 重建 ────────────────────────────────────────────────────

def _rebuild_embed(lottery: dict) -> discord.Embed:
    ltype        = lottery['type']
    closed       = lottery.get('closed', False)
    participants = lottery.get('participants', [])

    embed = discord.Embed(
        title     = f'🎫 簽到抽獎：{lottery["name"]}',
        color     = 0x95A5A6 if closed else TYPE_COLOR[ltype],
        timestamp = tw_now(),
    )
    embed.add_field(name='🎁 獎品',     value=lottery['prize'],               inline=True)
    embed.add_field(name='🎟️ 類型',     value=TYPE_LABEL[ltype],              inline=True)
    embed.add_field(name='🥇 中獎人數', value=f'{lottery["winner_count"]} 人', inline=True)
    embed.add_field(name='👑 發布者',   value=f'<@{lottery["creator_id"]}>',   inline=True)
    embed.add_field(name='👥 已參加',   value=f'**{len(participants)}** 人',    inline=True)

    if lottery.get('description'):
        embed.add_field(name='📝 說明', value=lottery['description'][:1024], inline=False)

    if participants:
        display = participants[:20]
        names   = '\n'.join(f'`{i+1}.` <@{uid}>' for i, uid in enumerate(display))
        if len(participants) > 20:
            names += f'\n*... 還有 {len(participants) - 20} 人*'
        embed.add_field(name='📋 參加名單', value=names[:1024], inline=False)

    if closed:
        embed.set_footer(text='🔒 此抽獎已結束')
    else:
        embed.set_footer(text=f'請使用【{TICKET_LABEL[ltype]}】參加 | 每人限一次')

    return embed


# ── 加入處理（共用）──────────────────────────────────────────────

async def _handle_join(interaction: discord.Interaction, ticket_type: str):
    mid     = str(interaction.message.id)
    gid     = str(interaction.guild_id)
    lottery = active_lotteries.get(gid, {}).get(mid)

    if not lottery:
        await interaction.response.send_message('❌ 此抽獎不存在或已結束。', ephemeral=True)
        return
    if lottery.get('closed'):
        await interaction.response.send_message('❌ 此抽獎已關閉。', ephemeral=True)
        return

    # 類型鎖定：只接受對應的抽獎卷
    if lottery['type'] != ticket_type:
        correct = TICKET_LABEL[lottery['type']]
        await interaction.response.send_message(
            f'❌ 此抽獎為**{TYPE_LABEL[lottery["type"]]}**，\n'
            f'只能使用**{correct}**參加！',
            ephemeral=True)
        return

    uid = str(interaction.user.id)
    if uid in lottery['participants']:
        await interaction.response.send_message('⚠️ 你已在此抽獎名單中！', ephemeral=True)
        return

    db      = interaction.client.db
    success, wallet = db.use_ticket(interaction.guild_id, interaction.user.id, ticket_type)
    if not success:
        await interaction.response.send_message(
            f'❌ 你沒有**{TICKET_LABEL[ticket_type]}**！\n'
            f'可在簽到面板點擊「🔄 兌換抽獎卷」用簽到幣兌換。',
            ephemeral=True)
        return

    lottery['participants'].append(uid)
    _save_lotteries()

    await interaction.response.defer()
    try:
        await interaction.message.edit(embed=_rebuild_embed(lottery))
    except Exception:
        pass

    remaining = wallet.get(TICKET_KEY[ticket_type], 0)
    await interaction.followup.send(
        f'✅ 已使用 1 張**{TICKET_LABEL[ticket_type]}**參加抽獎！\n剩餘：**{remaining}** 張',
        ephemeral=True)


# ── 批量對象解析（共用）──────────────────────────────────────────

def _resolve_targets(
    guild: discord.Guild,
    成員: Optional[discord.Member],
    身分組: Optional[discord.Role],
    全員: bool,
) -> tuple[list[discord.Member] | None, str]:
    """
    回傳 (targets, error_msg)。
    targets 為 None 代表驗證失敗，error_msg 說明原因。
    """
    specified = sum([成員 is not None, 身分組 is not None, 全員])
    if specified == 0:
        return None, '❌ 請指定對象：成員、身分組或全員，三擇一。'
    if specified > 1:
        return None, '❌ 請只選擇一種對象方式，不可同時選多種。'

    if 成員:
        return [成員], ''
    if 身分組:
        return [m for m in 身分組.members if not m.bot], ''
    # 全員
    return [m for m in guild.members if not m.bot], ''


# ── 公開抽獎 View（持久化）────────────────────────────────────────

class CheckinLotteryView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🗓️ 使用周抽獎卷參加', style=discord.ButtonStyle.success,
               custom_id='cklottery_join_weekly', row=0)
    async def join_weekly(self, interaction: discord.Interaction, button: ui.Button):
        await _handle_join(interaction, 'weekly')

    @ui.button(label='📅 使用月抽獎卷參加', style=discord.ButtonStyle.primary,
               custom_id='cklottery_join_monthly', row=0)
    async def join_monthly(self, interaction: discord.Interaction, button: ui.Button):
        await _handle_join(interaction, 'monthly')

    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.secondary,
               custom_id='cklottery_list', row=0)
    async def view_list(self, interaction: discord.Interaction, button: ui.Button):
        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return
        participants = lottery.get('participants', [])
        if not participants:
            await interaction.response.send_message('📭 目前沒有人參加。', ephemeral=True)
            return
        embed = discord.Embed(
            title = f'📋 {lottery["name"]} — 參加名單',
            color = TYPE_COLOR.get(lottery['type'], 0x5865F2),
        )
        embed.description = '\n'.join(
            f'`{i+1}.` <@{uid}>' for i, uid in enumerate(participants)
        )[:4096]
        embed.set_footer(text=f'共 {len(participants)} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label='🎲 開始抽獎', style=discord.ButtonStyle.danger,
               custom_id='cklottery_draw', row=1)
    async def draw(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        if not db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以開始抽獎。', ephemeral=True)
            return

        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return
        if lottery.get('closed'):
            await interaction.response.send_message('❌ 此抽獎已結束。', ephemeral=True)
            return

        participants = lottery['participants']
        winner_count = lottery['winner_count']
        if not participants:
            await interaction.response.send_message('❌ 尚無人參加！', ephemeral=True)
            return
        if len(participants) < winner_count:
            await interaction.response.send_message(
                f'❌ 參加人數（{len(participants)}）少於中獎人數（{winner_count}）。',
                ephemeral=True)
            return

        # 立即關閉防止重複觸發
        lottery['closed'] = True
        active_lotteries[gid].pop(mid, None)
        _save_lotteries()

        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.message.edit(
                embed=_rebuild_embed({**lottery, 'closed': True}), view=None)
        except Exception:
            pass

        channel         = interaction.channel
        countdown_embed = discord.Embed(
            title=f'🎰 抽獎即將開始：{lottery["name"]}', color=0xFF6B6B)
        msg = await channel.send(embed=countdown_embed)
        for i in [3, 2, 1]:
            countdown_embed.description = f'# {i}'
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        winner_ids = random.sample(participants, winner_count)

        result_embed = discord.Embed(
            title       = f'🏆 抽獎結果：{lottery["name"]}',
            description = f'🎁 **獎品：**{lottery["prize"]}',
            color       = 0x00FF88,
            timestamp   = tw_now(),
        )
        result_embed.add_field(
            name  = '🥇 中獎者',
            value = '\n'.join(f'│🏆 **{i+1}.** <@{uid}>' for i, uid in enumerate(winner_ids)),
            inline = False,
        )
        losers = [uid for uid in participants if uid not in winner_ids]
        if losers:
            result_embed.add_field(
                name  = '😢 未中獎',
                value = ', '.join(f'<@{uid}>' for uid in losers)[:1024],
                inline = False,
            )
        result_embed.add_field(
            name  = '📊 統計',
            value = f'參加人數：{len(participants)} 人\n中獎人數：{winner_count} 人',
            inline = False,
        )
        result_embed.set_footer(text=f'由 {interaction.user.display_name} 主持抽獎')

        await msg.edit(embed=result_embed)
        await channel.send('🎉 恭喜中獎！' + ' '.join(f'<@{uid}>' for uid in winner_ids))
        await interaction.followup.send('✅ 抽獎完成！', ephemeral=True)

    @ui.button(label='🔒 關閉抽獎', style=discord.ButtonStyle.secondary,
               custom_id='cklottery_close', row=1)
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        if not db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以關閉抽獎。', ephemeral=True)
            return

        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return

        lottery['closed'] = True
        active_lotteries[gid].pop(mid, None)
        _save_lotteries()

        await interaction.response.edit_message(
            embed=_rebuild_embed({**lottery, 'closed': True}), view=None)


# ── 建立抽獎表單 ──────────────────────────────────────────────────

class CheckinLotteryModal(ui.Modal):
    name         = ui.TextInput(label='抽獎名稱',
                                placeholder='例如：第一期周抽',
                                required=True, max_length=50)
    prize        = ui.TextInput(label='獎品說明',
                                placeholder='例如：限定裝備 x1',
                                required=True, max_length=200)
    winner_count = ui.TextInput(label='中獎人數',
                                placeholder='例如：3',
                                required=True, max_length=3)
    description  = ui.TextInput(label='活動說明（選填）',
                                style=discord.TextStyle.paragraph,
                                placeholder='填寫額外說明...',
                                required=False, max_length=300)

    def __init__(self, lottery_type: str):
        type_label = '周抽' if lottery_type == 'weekly' else '月抽'
        super().__init__(title=f'🎫 建立{type_label}活動')
        self.lottery_type = lottery_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.winner_count.value)
            if count < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 中獎人數必須是正整數！', ephemeral=True)
            return

        gs    = interaction.client.db.get_guild_settings(interaction.guild_id)
        ch_id = gs.get('checkin_lottery_channel')
        if not ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定簽到抽獎頻道！請管理員先使用 `/設定簽到抽獎頻道`。', ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message('❌ 找不到抽獎頻道，請重新設定。', ephemeral=True)
            return

        lottery = {
            'name':         self.name.value,
            'prize':        self.prize.value,
            'type':         self.lottery_type,
            'winner_count': count,
            'description':  self.description.value,
            'creator_id':   str(interaction.user.id),
            'channel_id':   str(channel.id),
            'guild_id':     str(interaction.guild_id),
            'participants': [],
            'closed':       False,
            'created_at':   tw_now().isoformat(),
        }

        msg = await channel.send(embed=_rebuild_embed(lottery), view=CheckinLotteryView())

        gid = str(interaction.guild_id)
        active_lotteries.setdefault(gid, {})[str(msg.id)] = lottery
        _save_lotteries()

        await interaction.response.send_message(
            f'✅ 抽獎已發布至 {channel.mention}！', ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback, sys
        traceback.print_exc(file=sys.stderr)
        try:
            await interaction.response.send_message('❌ 發生錯誤，請稍後再試。', ephemeral=True)
        except Exception:
            pass


# ── 管理員建立面板（非持久化）────────────────────────────────────

class LotteryAdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label='🗓️ 建立周抽', style=discord.ButtonStyle.success, row=0)
    async def create_weekly(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CheckinLotteryModal('weekly'))

    @ui.button(label='📅 建立月抽', style=discord.ButtonStyle.primary, row=0)
    async def create_monthly(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CheckinLotteryModal('monthly'))


# ── Cog ──────────────────────────────────────────────────────────

class CheckinLotteryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load_lotteries()
        bot.add_view(CheckinLotteryView())

    # ── /簽到抽獎面板 ────────────────────────────────────────────
    @app_commands.command(name='簽到抽獎面板', description='管理員建立簽到抽獎活動的操作面板')
    @admin_only()
    async def lottery_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '🎫 簽到抽獎系統',
            description = (
                '玩家使用**簽到幣兌換的抽獎卷**來參加抽獎！\n\n'
                '🗓️ **周抽獎卷**：7 枚簽到幣兌換 1 張\n'
                '📅 **月抽獎卷**：26 枚簽到幣兌換 1 張\n\n'
                '建立後抽獎公告自動發至已設定頻道，\n'
                '玩家只能用對應類型的抽獎卷參加。\n\n'
                '點擊下方按鈕建立抽獎：'
            ),
            color = 0xF1C40F,
        )
        await interaction.response.send_message(embed=embed, view=LotteryAdminPanelView(), ephemeral=True)

    # ── /設定簽到抽獎頻道 ────────────────────────────────────────
    @app_commands.command(name='設定簽到抽獎頻道', description='設定簽到抽獎公告發布的頻道（僅限管理員）')
    @app_commands.describe(頻道='抽獎公告將發布到此頻道')
    @admin_only()
    async def set_channel(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['checkin_lottery_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 簽到抽獎頻道已設定為 {頻道.mention}', ephemeral=True)

    # ── /發放抽獎卷 ──────────────────────────────────────────────
    @app_commands.command(name='發放抽獎卷', description='發放抽獎卷給指定成員／身分組／全員（僅限管理員）')
    @app_commands.describe(
        類型  = '抽獎卷類型',
        數量  = '發放張數',
        成員  = '單一成員（與身分組/全員三擇一）',
        身分組 = '整個身分組（與成員/全員三擇一）',
        全員  = '是否發放給伺服器全員（與成員/身分組三擇一）',
    )
    @app_commands.choices(類型=[
        app_commands.Choice(name='周抽獎卷', value='weekly'),
        app_commands.Choice(name='月抽獎卷', value='monthly'),
    ])
    @admin_only()
    async def give_tickets(
        self, interaction: discord.Interaction,
        類型: str, 數量: int,
        成員:  Optional[discord.Member] = None,
        身分組: Optional[discord.Role]   = None,
        全員:  bool = False,
    ):
        if 數量 < 1:
            await interaction.response.send_message('❌ 數量必須大於 0！', ephemeral=True)
            return
        targets, err = _resolve_targets(interaction.guild, 成員, 身分組, 全員)
        if targets is None:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        label = TICKET_LABEL[類型]

        if len(targets) == 1:
            new_count = self.bot.db.adjust_tickets(interaction.guild_id, targets[0].id, 類型, 數量)
            await interaction.followup.send(
                f'✅ 已為 {targets[0].mention} 發放 **{數量}** 張{label}\n'
                f'目前持有：**{new_count}** 張', ephemeral=True)
        else:
            self.bot.db.batch_adjust_tickets(
                interaction.guild_id, [m.id for m in targets], 類型, 數量)
            target_desc = f'**{身分組.name}** 身分組（{len(targets)} 人）' if 身分組 else f'全員（{len(targets)} 人）'
            await interaction.followup.send(
                f'✅ 已為 {target_desc} 各發放 **{數量}** 張{label}', ephemeral=True)

    # ── /扣除抽獎卷 ──────────────────────────────────────────────
    @app_commands.command(name='扣除抽獎卷', description='扣除指定成員／身分組／全員的抽獎卷（僅限管理員）')
    @app_commands.describe(
        類型  = '抽獎卷類型',
        數量  = '扣除張數',
        成員  = '單一成員（與身分組/全員三擇一）',
        身分組 = '整個身分組（與成員/全員三擇一）',
        全員  = '是否扣除全員（與成員/身分組三擇一）',
    )
    @app_commands.choices(類型=[
        app_commands.Choice(name='周抽獎卷', value='weekly'),
        app_commands.Choice(name='月抽獎卷', value='monthly'),
    ])
    @admin_only()
    async def remove_tickets(
        self, interaction: discord.Interaction,
        類型: str, 數量: int,
        成員:  Optional[discord.Member] = None,
        身分組: Optional[discord.Role]   = None,
        全員:  bool = False,
    ):
        if 數量 < 1:
            await interaction.response.send_message('❌ 數量必須大於 0！', ephemeral=True)
            return
        targets, err = _resolve_targets(interaction.guild, 成員, 身分組, 全員)
        if targets is None:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        label = TICKET_LABEL[類型]

        if len(targets) == 1:
            new_count = self.bot.db.adjust_tickets(interaction.guild_id, targets[0].id, 類型, -數量)
            await interaction.followup.send(
                f'✅ 已扣除 {targets[0].mention} **{數量}** 張{label}\n'
                f'目前持有：**{new_count}** 張', ephemeral=True)
        else:
            self.bot.db.batch_adjust_tickets(
                interaction.guild_id, [m.id for m in targets], 類型, -數量)
            target_desc = f'**{身分組.name}** 身分組（{len(targets)} 人）' if 身分組 else f'全員（{len(targets)} 人）'
            await interaction.followup.send(
                f'✅ 已扣除 {target_desc} 各 **{數量}** 張{label}', ephemeral=True)

    # ── /發放簽到幣 ──────────────────────────────────────────────
    @app_commands.command(name='發放簽到幣', description='發放簽到幣給指定成員／身分組／全員（僅限管理員）')
    @app_commands.describe(
        數量  = '發放枚數',
        成員  = '單一成員（與身分組/全員三擇一）',
        身分組 = '整個身分組（與成員/全員三擇一）',
        全員  = '是否發放給伺服器全員（與成員/身分組三擇一）',
    )
    @admin_only()
    async def give_coins(
        self, interaction: discord.Interaction,
        數量: int,
        成員:  Optional[discord.Member] = None,
        身分組: Optional[discord.Role]   = None,
        全員:  bool = False,
    ):
        if 數量 < 1:
            await interaction.response.send_message('❌ 數量必須大於 0！', ephemeral=True)
            return
        targets, err = _resolve_targets(interaction.guild, 成員, 身分組, 全員)
        if targets is None:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if len(targets) == 1:
            new_coins = self.bot.db.add_coins(interaction.guild_id, targets[0].id, 數量)
            await interaction.followup.send(
                f'✅ 已為 {targets[0].mention} 發放 **{數量}** 枚簽到幣\n'
                f'目前持有：**{new_coins}** 枚', ephemeral=True)
        else:
            self.bot.db.batch_adjust_coins(interaction.guild_id, [m.id for m in targets], 數量)
            target_desc = f'**{身分組.name}** 身分組（{len(targets)} 人）' if 身分組 else f'全員（{len(targets)} 人）'
            await interaction.followup.send(
                f'✅ 已為 {target_desc} 各發放 **{數量}** 枚簽到幣', ephemeral=True)

    # ── /扣除簽到幣 ──────────────────────────────────────────────
    @app_commands.command(name='扣除簽到幣', description='扣除指定成員／身分組／全員的簽到幣（僅限管理員）')
    @app_commands.describe(
        數量  = '扣除枚數',
        成員  = '單一成員（與身分組/全員三擇一）',
        身分組 = '整個身分組（與成員/全員三擇一）',
        全員  = '是否扣除全員（與成員/身分組三擇一）',
    )
    @admin_only()
    async def remove_coins(
        self, interaction: discord.Interaction,
        數量: int,
        成員:  Optional[discord.Member] = None,
        身分組: Optional[discord.Role]   = None,
        全員:  bool = False,
    ):
        if 數量 < 1:
            await interaction.response.send_message('❌ 數量必須大於 0！', ephemeral=True)
            return
        targets, err = _resolve_targets(interaction.guild, 成員, 身分組, 全員)
        if targets is None:
            await interaction.response.send_message(err, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if len(targets) == 1:
            new_coins = self.bot.db.add_coins(interaction.guild_id, targets[0].id, -數量)
            await interaction.followup.send(
                f'✅ 已扣除 {targets[0].mention} **{數量}** 枚簽到幣\n'
                f'目前持有：**{new_coins}** 枚', ephemeral=True)
        else:
            self.bot.db.batch_adjust_coins(interaction.guild_id, [m.id for m in targets], -數量)
            target_desc = f'**{身分組.name}** 身分組（{len(targets)} 人）' if 身分組 else f'全員（{len(targets)} 人）'
            await interaction.followup.send(
                f'✅ 已扣除 {target_desc} 各 **{數量}** 枚簽到幣', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CheckinLotteryCog(bot))
