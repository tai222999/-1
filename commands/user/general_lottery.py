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
LOTTERY_FILE       = 'general_lotteries.json'
MULTI_LOTTERY_FILE = 'general_multi_lotteries.json'
LOTTERY_COLOR      = 0x3498DB
MULTI_COLOR        = 0x9B59B6

active_lotteries:       dict = {}   # {guild_id_str: {msg_id_str: {...}}}
active_multi_lotteries: dict = {}   # {guild_id_str: {msg_id_str: {...}}}


def tw_now() -> datetime:
    return datetime.now(TW_TZ)


# ── 資料存取 ──────────────────────────────────────────────────────

def _load_lotteries():
    global active_lotteries
    raw = _load(LOTTERY_FILE)
    active_lotteries = raw if isinstance(raw, dict) else {}

def _save_lotteries():
    _save(LOTTERY_FILE, active_lotteries)

def _load_multi_lotteries():
    global active_multi_lotteries
    raw = _load(MULTI_LOTTERY_FILE)
    active_multi_lotteries = raw if isinstance(raw, dict) else {}

def _save_multi_lotteries():
    _save(MULTI_LOTTERY_FILE, active_multi_lotteries)

def _parse_prizes(text: str) -> list | None:
    """解析獎品清單文字，格式：獎品名稱:人數（每行一個）。"""
    prizes = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if ':' not in line:
            return None
        name, _, count_str = line.rpartition(':')
        name = name.strip()
        if not name:
            return None
        try:
            count = int(count_str.strip())
            if count < 1:
                return None
        except ValueError:
            return None
        prizes.append({'name': name, 'count': count})
    return prizes if prizes else None


# ── 普通抽獎 Embed ────────────────────────────────────────────────

def _rebuild_embed(lottery: dict) -> discord.Embed:
    closed       = lottery.get('closed', False)
    participants = lottery.get('participants', [])

    embed = discord.Embed(
        title     = f'🎉 普通抽獎：{lottery["name"]}',
        color     = 0x95A5A6 if closed else LOTTERY_COLOR,
        timestamp = tw_now(),
    )
    embed.add_field(name='🎁 獎品',     value=lottery['prize'],               inline=True)
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
        embed.set_footer(text='免費參加！點擊下方按鈕即可報名 | 每人限一次')

    return embed


# ── 多重抽獎 Embed ────────────────────────────────────────────────

def _rebuild_multi_embed(lottery: dict) -> discord.Embed:
    closed       = lottery.get('closed', False)
    participants = lottery.get('participants', [])
    prizes       = lottery.get('prizes', [])

    embed = discord.Embed(
        title     = f'🎊 多重抽獎：{lottery["name"]}',
        color     = 0x95A5A6 if closed else MULTI_COLOR,
        timestamp = tw_now(),
    )

    prize_text    = '\n'.join(f'🎁 **{p["name"]}** × {p["count"]} 人' for p in prizes)
    total_winners = sum(p['count'] for p in prizes)
    embed.add_field(name='🎁 獎品清單',   value=prize_text or '（無）',              inline=False)
    embed.add_field(name='🥇 總中獎人數', value=f'{total_winners} 人',               inline=True)
    embed.add_field(name='👑 發布者',     value=f'<@{lottery["creator_id"]}>',        inline=True)
    embed.add_field(name='👥 已參加',     value=f'**{len(participants)}** 人',        inline=True)

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
        embed.set_footer(text='免費參加！點擊下方按鈕即可報名 | 每人限一次')

    return embed


# ── 普通抽獎 View（持久化）────────────────────────────────────────

class GeneralLotteryView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🎉 參加抽獎', style=discord.ButtonStyle.success,
               custom_id='glottery_join', row=0)
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_lotteries.get(gid, {}).get(mid)

        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在或已結束。', ephemeral=True)
            return
        if lottery.get('closed'):
            await interaction.response.send_message('❌ 此抽獎已關閉。', ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid in lottery['participants']:
            await interaction.response.send_message('⚠️ 你已在此抽獎名單中！', ephemeral=True)
            return

        lottery['participants'].append(uid)
        _save_lotteries()

        await interaction.response.defer()
        try:
            await interaction.message.edit(embed=_rebuild_embed(lottery))
        except Exception:
            pass

        await interaction.followup.send('✅ 已成功報名參加抽獎！祝你好運 🍀', ephemeral=True)

    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.secondary,
               custom_id='glottery_list', row=0)
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
            color = LOTTERY_COLOR,
        )
        embed.description = '\n'.join(
            f'`{i+1}.` <@{uid}>' for i, uid in enumerate(participants)
        )[:4096]
        embed.set_footer(text=f'共 {len(participants)} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label='🎲 開始抽獎', style=discord.ButtonStyle.danger,
               custom_id='glottery_draw', row=1)
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
        await channel.send(
            '🎉 恭喜 ' + ' '.join(f'<@{uid}>' for uid in winner_ids)
            + f' 抽中了「{lottery["prize"]}」！🎁'
        )
        await interaction.followup.send('✅ 抽獎完成！', ephemeral=True)

    @ui.button(label='🔒 關閉抽獎', style=discord.ButtonStyle.secondary,
               custom_id='glottery_close', row=1)
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


# ── 多重抽獎 View（持久化）────────────────────────────────────────

class MultiPrizeLotteryView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🎉 參加抽獎', style=discord.ButtonStyle.success,
               custom_id='mglottery_join', row=0)
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_multi_lotteries.get(gid, {}).get(mid)

        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在或已結束。', ephemeral=True)
            return
        if lottery.get('closed'):
            await interaction.response.send_message('❌ 此抽獎已關閉。', ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid in lottery['participants']:
            await interaction.response.send_message('⚠️ 你已在此抽獎名單中！', ephemeral=True)
            return

        lottery['participants'].append(uid)
        _save_multi_lotteries()

        await interaction.response.defer()
        try:
            await interaction.message.edit(embed=_rebuild_multi_embed(lottery))
        except Exception:
            pass

        await interaction.followup.send('✅ 已成功報名參加抽獎！祝你好運 🍀', ephemeral=True)

    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.secondary,
               custom_id='mglottery_list', row=0)
    async def view_list(self, interaction: discord.Interaction, button: ui.Button):
        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_multi_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return
        participants = lottery.get('participants', [])
        if not participants:
            await interaction.response.send_message('📭 目前沒有人參加。', ephemeral=True)
            return
        embed = discord.Embed(
            title = f'📋 {lottery["name"]} — 參加名單',
            color = MULTI_COLOR,
        )
        embed.description = '\n'.join(
            f'`{i+1}.` <@{uid}>' for i, uid in enumerate(participants)
        )[:4096]
        embed.set_footer(text=f'共 {len(participants)} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label='🎲 開始抽獎', style=discord.ButtonStyle.danger,
               custom_id='mglottery_draw', row=1)
    async def draw(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        if not db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以開始抽獎。', ephemeral=True)
            return

        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_multi_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return
        if lottery.get('closed'):
            await interaction.response.send_message('❌ 此抽獎已結束。', ephemeral=True)
            return

        participants  = lottery['participants']
        prizes        = lottery['prizes']
        total_winners = sum(p['count'] for p in prizes)

        if not participants:
            await interaction.response.send_message('❌ 尚無人參加！', ephemeral=True)
            return
        if len(participants) < total_winners:
            await interaction.response.send_message(
                f'❌ 參加人數（{len(participants)}）少於總中獎人數（{total_winners}）。',
                ephemeral=True)
            return

        # 立即關閉防止重複觸發
        lottery['closed'] = True
        active_multi_lotteries[gid].pop(mid, None)
        _save_multi_lotteries()

        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.message.edit(
                embed=_rebuild_multi_embed({**lottery, 'closed': True}), view=None)
        except Exception:
            pass

        channel         = interaction.channel
        countdown_embed = discord.Embed(
            title=f'🎰 多重抽獎即將開始：{lottery["name"]}', color=0xFF6B6B)
        msg = await channel.send(embed=countdown_embed)
        for i in [3, 2, 1]:
            countdown_embed.description = f'# {i}'
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        # 依序對每個獎品從剩餘名單中抽取，中過獎的人不再參加後續抽獎
        pool              = list(participants)
        winners_by_prize  = []
        for prize_info in prizes:
            count = min(prize_info['count'], len(pool))
            won   = random.sample(pool, count) if count else []
            pool  = [uid for uid in pool if uid not in won]
            winners_by_prize.append((prize_info['name'], won))

        # 結果 Embed
        result_embed = discord.Embed(
            title     = f'🏆 多重抽獎結果：{lottery["name"]}',
            color     = 0x00FF88,
            timestamp = tw_now(),
        )
        for prize_name, uids in winners_by_prize:
            value = ('\n'.join(f'│🏆 <@{uid}>' for uid in uids)
                     if uids else '（人數不足，無人中獎）')
            result_embed.add_field(name=f'🎁 {prize_name}', value=value, inline=False)

        all_winners = [uid for _, uids in winners_by_prize for uid in uids]
        losers      = [uid for uid in participants if uid not in all_winners]
        if losers:
            result_embed.add_field(
                name  = '😢 未中獎',
                value = ', '.join(f'<@{uid}>' for uid in losers)[:1024],
                inline = False,
            )
        result_embed.add_field(
            name  = '📊 統計',
            value = f'參加人數：{len(participants)} 人\n中獎人數：{len(all_winners)} 人',
            inline = False,
        )
        result_embed.set_footer(text=f'由 {interaction.user.display_name} 主持抽獎')

        await msg.edit(embed=result_embed)

        # 個別通知：每人一行，說明抽中的獎品
        lines = [
            f'<@{uid}> 抽中了「{prize_name}」'
            for prize_name, uids in winners_by_prize
            for uid in uids
        ]
        if lines:
            await channel.send('🎉 恭喜以下成員中獎！\n' + '\n'.join(lines))

        await interaction.followup.send('✅ 抽獎完成！', ephemeral=True)

    @ui.button(label='🔒 關閉抽獎', style=discord.ButtonStyle.secondary,
               custom_id='mglottery_close', row=1)
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        db = interaction.client.db
        if not db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以關閉抽獎。', ephemeral=True)
            return

        mid     = str(interaction.message.id)
        gid     = str(interaction.guild_id)
        lottery = active_multi_lotteries.get(gid, {}).get(mid)
        if not lottery:
            await interaction.response.send_message('❌ 此抽獎不存在。', ephemeral=True)
            return

        lottery['closed'] = True
        active_multi_lotteries[gid].pop(mid, None)
        _save_multi_lotteries()

        await interaction.response.edit_message(
            embed=_rebuild_multi_embed({**lottery, 'closed': True}), view=None)


# ── 普通抽獎表單 ──────────────────────────────────────────────────

class GeneralLotteryModal(ui.Modal, title='🎉 建立普通抽獎'):
    name         = ui.TextInput(label='抽獎名稱',
                                placeholder='例如：本週抽獎活動',
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

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.winner_count.value)
            if count < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 中獎人數必須是正整數！', ephemeral=True)
            return

        gs    = interaction.client.db.get_guild_settings(interaction.guild_id)
        ch_id = gs.get('general_lottery_channel')
        if not ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定普通抽獎頻道！請管理員先使用 `/設定普通抽獎頻道`。', ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message('❌ 找不到抽獎頻道，請重新設定。', ephemeral=True)
            return

        lottery = {
            'name':         self.name.value,
            'prize':        self.prize.value,
            'winner_count': count,
            'description':  self.description.value,
            'creator_id':   str(interaction.user.id),
            'channel_id':   str(channel.id),
            'guild_id':     str(interaction.guild_id),
            'participants': [],
            'closed':       False,
            'created_at':   tw_now().isoformat(),
        }

        msg = await channel.send(embed=_rebuild_embed(lottery), view=GeneralLotteryView())

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


# ── 多重抽獎表單 ──────────────────────────────────────────────────

class MultiPrizeLotteryModal(ui.Modal, title='🎊 建立多重抽獎'):
    name        = ui.TextInput(label='抽獎名稱',
                               placeholder='例如：本週多重抽獎活動',
                               required=True, max_length=50)
    prizes_text = ui.TextInput(
        label       = '獎品清單（格式：獎品名稱:人數，一行一個）',
        style       = discord.TextStyle.paragraph,
        placeholder = '例如：\n傳說武器:1\n稀有裝備:2\n普通道具:5',
        required    = True,
        max_length  = 800,
    )
    description = ui.TextInput(label='活動說明（選填）',
                               style=discord.TextStyle.paragraph,
                               placeholder='填寫額外說明...',
                               required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        prizes = _parse_prizes(self.prizes_text.value)
        if prizes is None:
            await interaction.response.send_message(
                '❌ 獎品格式錯誤！請使用「獎品名稱:人數」格式，每行一個。\n'
                '範例：\n```\n傳說武器:1\n稀有裝備:2\n普通道具:5\n```',
                ephemeral=True)
            return

        gs    = interaction.client.db.get_guild_settings(interaction.guild_id)
        ch_id = gs.get('general_lottery_channel')
        if not ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定普通抽獎頻道！請管理員先使用 `/設定普通抽獎頻道`。', ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message('❌ 找不到抽獎頻道，請重新設定。', ephemeral=True)
            return

        lottery = {
            'name':         self.name.value,
            'prizes':       prizes,
            'description':  self.description.value,
            'creator_id':   str(interaction.user.id),
            'channel_id':   str(channel.id),
            'guild_id':     str(interaction.guild_id),
            'participants': [],
            'closed':       False,
            'created_at':   tw_now().isoformat(),
        }

        msg = await channel.send(embed=_rebuild_multi_embed(lottery), view=MultiPrizeLotteryView())

        gid = str(interaction.guild_id)
        active_multi_lotteries.setdefault(gid, {})[str(msg.id)] = lottery
        _save_multi_lotteries()

        await interaction.response.send_message(
            f'✅ 多重抽獎已發布至 {channel.mention}！', ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback, sys
        traceback.print_exc(file=sys.stderr)
        try:
            await interaction.response.send_message('❌ 發生錯誤，請稍後再試。', ephemeral=True)
        except Exception:
            pass


# ── 管理員建立面板（非持久化）────────────────────────────────────

class GeneralLotteryAdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label='🎉 建立抽獎', style=discord.ButtonStyle.success, row=0)
    async def create(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(GeneralLotteryModal())

    @ui.button(label='🎊 多重抽獎', style=discord.ButtonStyle.primary, row=0)
    async def create_multi(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MultiPrizeLotteryModal())


# ── Cog ──────────────────────────────────────────────────────────

class GeneralLotteryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load_lotteries()
        _load_multi_lotteries()
        bot.add_view(GeneralLotteryView())
        bot.add_view(MultiPrizeLotteryView())

    # ── /普通抽獎面板 ────────────────────────────────────────────
    @app_commands.command(name='普通抽獎面板', description='管理員建立普通抽獎活動的操作面板')
    @admin_only()
    async def lottery_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '🎉 普通抽獎系統',
            description = (
                '免費參加的抽獎活動，無需任何票券！\n\n'
                '任何成員只需點擊抽獎公告中的**參加抽獎**按鈕即可報名，\n'
                '每人限報名一次，由管理員手動開始抽獎。\n\n'
                '🎉 **普通抽獎** — 單一獎品，指定中獎人數\n'
                '🎊 **多重抽獎** — 多種獎品，每種獎品各自指定人數\n'
                '（多重抽獎中，每位參加者最多只能中一個獎品）\n\n'
                '建立後抽獎公告自動發至已設定頻道。\n\n'
                '點擊下方按鈕建立抽獎：'
            ),
            color = LOTTERY_COLOR,
        )
        await interaction.response.send_message(
            embed=embed, view=GeneralLotteryAdminPanelView(), ephemeral=True)

    # ── /設定普通抽獎頻道 ────────────────────────────────────────
    @app_commands.command(name='設定普通抽獎頻道', description='設定普通抽獎公告發布的頻道（僅限管理員）')
    @app_commands.describe(頻道='抽獎公告將發布到此頻道')
    @admin_only()
    async def set_channel(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['general_lottery_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 普通抽獎頻道已設定為 {頻道.mention}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralLotteryCog(bot))
