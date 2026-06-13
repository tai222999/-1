import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from utils.database import _load, _save
from utils.helpers import admin_only

TW_TZ = timezone(timedelta(hours=8))

def tw_now() -> datetime:
    return datetime.now(TW_TZ)

PENDING_FILE  = 'donation_pending.json'
STORAGE_FILE  = 'donation_storage.json'
LOTTERY_FILE  = 'donation_lotteries.json'
EXPIRE_HOURS  = 6

ICON  = {'裝備': '⚔️', '卷軸': '📜', '其他物品': '📦'}
COLOR = {'裝備': 0xE74C3C, '卷軸': 0x9B59B6, '其他物品': 0x3498DB}

# 進行中的捐獻抽獎 {guild_id(int): lottery_data}
# participants 欄位為 list[{'id': int, 'name': str}]
active_donation_lotteries: dict[int, dict] = {}
donation_scheduled_tasks:  dict[int, dict] = {}   # {guild_id: task_info}


# ── 資料存取 ──────────────────────────────────────────────────────

def _load_pending() -> dict:
    return _load(PENDING_FILE)

def _save_pending(data: dict):
    _save(PENDING_FILE, data)

def _load_storage() -> list:
    data = _load(STORAGE_FILE)
    return data.get('items', []) if isinstance(data, dict) else []

def _save_storage(items: list):
    _save(STORAGE_FILE, {'items': items})

def _dt_to_str(dt) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else dt

def _str_to_dt(s) -> datetime | None:
    if isinstance(s, str):
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return s

def _save_lotteries():
    lotteries_data = {}
    for gid, lottery in active_donation_lotteries.items():
        entry = {**lottery}
        entry['created_at'] = _dt_to_str(entry.get('created_at'))
        entry['draw_time']  = _dt_to_str(entry.get('draw_time'))
        lotteries_data[str(gid)] = entry

    tasks_data = {}
    for gid, task in donation_scheduled_tasks.items():
        entry = {**task}
        entry['draw_time'] = _dt_to_str(entry.get('draw_time'))
        tasks_data[str(gid)] = entry

    _save(LOTTERY_FILE, {'lotteries': lotteries_data, 'scheduled_tasks': tasks_data})

def _load_lotteries():
    global active_donation_lotteries, donation_scheduled_tasks
    data = _load(LOTTERY_FILE)
    if not isinstance(data, dict):
        return

    for gid_str, lottery in data.get('lotteries', {}).items():
        entry = {**lottery}
        entry['created_at'] = _str_to_dt(entry.get('created_at'))
        entry['draw_time']  = _str_to_dt(entry.get('draw_time'))
        if not isinstance(entry.get('participants'), list):
            entry['participants'] = []
        active_donation_lotteries[int(gid_str)] = entry

    for gid_str, task in data.get('scheduled_tasks', {}).items():
        entry = {**task}
        dt = _str_to_dt(entry.get('draw_time'))
        if dt is None:
            continue
        entry['draw_time'] = dt
        donation_scheduled_tasks[int(gid_str)] = entry


# ── 捐獻類型選擇面板（ephemeral，暫時性）────────────────────────

class DonationTypeView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label='⚔️ 裝備', style=discord.ButtonStyle.primary, row=0)
    async def equipment_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(EquipmentModal())

    @ui.button(label='📜 卷軸', style=discord.ButtonStyle.secondary, row=0)
    async def scroll_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ScrollModal())

    @ui.button(label='📦 其他物品', style=discord.ButtonStyle.secondary, row=0)
    async def other_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(OtherItemModal())


# ── 裝備捐獻表單 ──────────────────────────────────────────────────

class EquipmentModal(ui.Modal, title='⚔️ 捐獻裝備'):
    item_name    = ui.TextInput(label='裝備名稱', placeholder='例如：黑天使之手套',
                                required=True, max_length=50)
    enhancement  = ui.TextInput(label='強化等級（+幾 AD / AP）',
                                placeholder='例如：+12 AD  /  +7 AP  /  無強化',
                                required=True, max_length=30)
    scrolls_left = ui.TextInput(label='剩餘捲數', placeholder='例如：7  /  0（無剩餘）',
                                required=True, max_length=10)
    potential    = ui.TextInput(label='潛能（藍/紫/黃/綠框 + 內容）',
                                style=discord.TextStyle.paragraph,
                                placeholder='例如：紫框 - 攻擊力+9%、忽無+4%\n無潛能請填「無」',
                                required=True, max_length=200)
    is_free      = ui.TextInput(label='是否無償捐獻（填「是」或「否」）',
                                placeholder='是 / 否', required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        is_free = self.is_free.value.strip() in ('是', '是的', 'yes', 'Yes', 'YES', 'Y', 'y')
        details = {
            'item_name':    self.item_name.value,
            'enhancement':  self.enhancement.value,
            'scrolls_left': self.scrolls_left.value,
            'potential':    self.potential.value,
            'is_free':      is_free,
        }
        await _post_donation(interaction, '裝備', self.item_name.value, details, is_free)


# ── 卷軸捐獻表單 ──────────────────────────────────────────────────

class ScrollModal(ui.Modal, title='📜 捐獻卷軸'):
    item_name = ui.TextInput(label='卷軸名稱', placeholder='例如：10% 攻擊力卷軸',
                             required=True, max_length=80)
    quantity  = ui.TextInput(label='捐獻數量', placeholder='例如：5',
                             required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        details = {'item_name': self.item_name.value, 'quantity': self.quantity.value}
        await _post_donation(interaction, '卷軸', self.item_name.value, details, is_free=True)


# ── 其他物品捐獻表單 ──────────────────────────────────────────────

class OtherItemModal(ui.Modal, title='📦 捐獻其他物品'):
    item_name = ui.TextInput(label='物品名稱', placeholder='例如：奇蹟魔方',
                             required=True, max_length=80)
    quantity  = ui.TextInput(label='捐獻數量', placeholder='例如：10',
                             required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        details = {'item_name': self.item_name.value, 'quantity': self.quantity.value}
        await _post_donation(interaction, '其他物品', self.item_name.value, details, is_free=True)


# ── 發布捐獻通知到頻道 ────────────────────────────────────────────

async def _post_donation(
    interaction: discord.Interaction,
    item_type: str,
    item_name: str,
    details: dict,
    is_free: bool,
):
    gs    = interaction.client.db.get_guild_settings(interaction.guild_id)
    ch_id = gs.get('donation_channel')
    if not ch_id:
        await interaction.response.send_message(
            '❌ 尚未設定捐獻頻道！請管理員先使用 `/設定捐獻頻道` 設定。', ephemeral=True)
        return

    channel = interaction.guild.get_channel(int(ch_id))
    if not channel:
        await interaction.response.send_message('❌ 找不到捐獻頻道，請重新設定。', ephemeral=True)
        return

    embed = discord.Embed(
        title=f'{ICON.get(item_type,"📦")} 捐獻通知：{item_name}',
        color=COLOR.get(item_type, 0x5865F2),
        timestamp=tw_now(),
    )
    embed.add_field(name='捐獻者',   value=interaction.user.mention,               inline=True)
    embed.add_field(name='類型',     value=item_type,                              inline=True)
    embed.add_field(name='是否無償', value='✅ 無償' if is_free else '💰 有償',     inline=True)
    if item_type == '裝備':
        embed.add_field(name='裝備名稱', value=details['item_name'],    inline=True)
        embed.add_field(name='強化等級', value=details['enhancement'],  inline=True)
        embed.add_field(name='剩餘捲數', value=details['scrolls_left'], inline=True)
        embed.add_field(name='潛能',     value=details['potential'],    inline=False)
    else:
        embed.add_field(name='物品名稱', value=details['item_name'], inline=True)
        embed.add_field(name='數量',     value=details['quantity'],  inline=True)
    embed.set_footer(text=f'管理員請在 {EXPIRE_HOURS} 小時內點擊「✅ 接收入庫」，逾期自動失效')

    try:
        msg = await channel.send(embed=embed, view=DonationAcceptView())
    except Exception as e:
        await interaction.response.send_message(f'❌ 無法發送到捐獻頻道：{e}', ephemeral=True)
        return

    pending = _load_pending()
    pending[str(msg.id)] = {
        'type':       item_type,
        'name':       item_name,
        'details':    details,
        'is_free':    is_free,
        'donor':      str(interaction.user),
        'donor_id':   str(interaction.user.id),
        'channel_id': str(channel.id),
        'guild_id':   str(interaction.guild_id),
        'created_at': tw_now().isoformat(),
    }
    _save_pending(pending)
    await interaction.response.send_message(
        f'✅ 捐獻申請已送出！等待管理員確認後入庫。\n📌 {channel.mention}', ephemeral=True)


# ── 接收入庫按鈕（持久化）────────────────────────────────────────

class DonationAcceptView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='✅ 接收入庫', style=discord.ButtonStyle.success,
               custom_id='donation_accept', row=0)
    async def accept_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.client.db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以接收捐獻。', ephemeral=True)
            return

        mid      = str(interaction.message.id)
        pending  = _load_pending()
        donation = pending.get(mid)
        if not donation:
            await interaction.response.send_message(
                '❌ 此捐獻已過期、已被接收，或不存在。', ephemeral=True)
            return

        created = datetime.fromisoformat(donation['created_at'])
        if (tw_now() - created) > timedelta(hours=EXPIRE_HOURS):
            del pending[mid]
            _save_pending(pending)
            embed = interaction.message.embeds[0]
            embed.color = 0x95A5A6
            embed.title = f'[已失效] {embed.title}'
            embed.set_footer(text='⏰ 超過 6 小時未被接收，已自動失效')
            await interaction.response.edit_message(embed=embed, view=None)
            return

        item_id = str(uuid.uuid4())[:8].upper()
        storage = _load_storage()
        storage.append({
            'id':             item_id,
            'type':           donation['type'],
            'name':           donation['name'],
            'details':        donation['details'],
            'is_free':        donation['is_free'],
            'donor':          donation['donor'],
            'donor_id':       donation['donor_id'],
            'received_at':    tw_now().isoformat(),
            'received_by':    str(interaction.user),
            'received_by_id': str(interaction.user.id),
        })
        _save_storage(storage)
        del pending[mid]
        _save_pending(pending)

        embed = interaction.message.embeds[0]
        embed.color = 0x2ECC71
        embed.set_footer(
            text=f'✅ 已由 {interaction.user.display_name} 接收入庫 | 物品 ID：{item_id}')
        await interaction.response.edit_message(embed=embed, view=None)


# ── 捐獻面板（持久化）────────────────────────────────────────────

class DonationPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🎁 捐獻', style=discord.ButtonStyle.success,
               custom_id='donation_donate', row=0)
    async def donate_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title='🎁 選擇捐獻類型',
            description=(
                '**⚔️ 裝備** — 填寫強化、潛能等詳細資料\n'
                '**📜 卷軸** — 填寫卷軸名稱與數量\n'
                '**📦 其他物品** — 填寫物品名稱與數量'
            ),
            color=0x5865F2,
        )
        await interaction.response.send_message(
            embed=embed, view=DonationTypeView(), ephemeral=True)


# ═══════════════════════════════════════════════════════════════════
#  捐獻抽獎系統
# ═══════════════════════════════════════════════════════════════════

async def _update_lottery_embed(interaction: discord.Interaction, lottery: dict):
    """更新管理面板 embed 上的成員列表。"""
    participants = lottery['participants']
    total = len(participants)
    if total == 0:
        member_list = '尚未加入任何成員'
    elif total <= 20:
        member_list = '\n'.join(
            f'│`{i+1:>2}.` {p["name"]}'
            for i, p in enumerate(participants)
        )
    else:
        first = '\n'.join(
            f'│`{i+1:>2}.` {p["name"]}'
            for i, p in enumerate(participants[:10])
        )
        member_list = f'{first}\n│... 共 {total} 人 ...'

    embed = interaction.message.embeds[0]
    for i, field in enumerate(embed.fields):
        if '已指定成員' in field.name:
            embed.set_field_at(
                i,
                name=f'👥 已指定成員（共 {total} 人）',
                value=member_list[:1024],
                inline=False,
            )
            break
    await interaction.response.edit_message(embed=embed)


# ── 手動選擇成員 ──────────────────────────────────────────────────

class DonationLotteryMemberSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder='👤 手動選擇成員…',
                         min_values=1, max_values=25, row=0,
                         custom_id='donation_lottery_member_select')

    async def callback(self, interaction: discord.Interaction):
        lottery = active_donation_lotteries.get(interaction.guild_id)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True)
            return
        if interaction.user.id != lottery['creator']:
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True)
            return
        existing = {p['id'] for p in lottery['participants']}
        added = [{'id': m.id, 'name': m.display_name}
                 for m in self.values if m.id not in existing and not m.bot]
        if not added:
            await interaction.response.send_message('⚠️ 所選成員已在名單中或為機器人。', ephemeral=True)
            return
        lottery['participants'].extend(added)
        _save_lotteries()
        await _update_lottery_embed(interaction, lottery)


# ── 身份組批量加入 ────────────────────────────────────────────────

class DonationLotteryRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder='🏷️ 選擇身份組（整組加入）…',
                         min_values=1, max_values=10, row=1,
                         custom_id='donation_lottery_role_select')

    async def callback(self, interaction: discord.Interaction):
        lottery = active_donation_lotteries.get(interaction.guild_id)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True)
            return
        if interaction.user.id != lottery['creator']:
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True)
            return
        existing = {p['id'] for p in lottery['participants']}
        added = []
        for role in self.values:
            for member in role.members:
                if member.id not in existing and not member.bot:
                    added.append({'id': member.id, 'name': member.display_name})
                    existing.add(member.id)
        if not added:
            await interaction.response.send_message('⚠️ 該身份組的成員都已在名單中。', ephemeral=True)
            return
        lottery['participants'].extend(added)
        _save_lotteries()
        await _update_lottery_embed(interaction, lottery)


# ── 抽獎管理面板（持久化）────────────────────────────────────────

class DonationLotteryManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DonationLotteryMemberSelect())
        self.add_item(DonationLotteryRoleSelect())

    @staticmethod
    def _get_lottery(interaction: discord.Interaction):
        return active_donation_lotteries.get(interaction.guild_id)

    @staticmethod
    def _is_creator(interaction: discord.Interaction, lottery: dict) -> bool:
        return lottery is not None and interaction.user.id == lottery['creator']

    # ── 加入頻道全員 ──────────────────────────────────────────────
    @ui.button(label='🟢 加入頻道全員', style=discord.ButtonStyle.primary,
               custom_id='donation_lottery_add_channel', row=2)
    async def add_channel_btn(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery(interaction)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True); return
        if not self._is_creator(interaction, lottery):
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True); return
        existing = {p['id'] for p in lottery['participants']}
        added = [{'id': m.id, 'name': m.display_name}
                 for m in interaction.channel.members if m.id not in existing and not m.bot]
        if not added:
            await interaction.response.send_message('⚠️ 頻道內所有成員都已在名單中。', ephemeral=True); return
        lottery['participants'].extend(added)
        _save_lotteries()
        await _update_lottery_embed(interaction, lottery)

    # ── 開始抽獎 ──────────────────────────────────────────────────
    @ui.button(label='🎲 開始抽獎', style=discord.ButtonStyle.success,
               custom_id='donation_lottery_draw', row=3)
    async def draw_btn(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery(interaction)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True); return
        if not self._is_creator(interaction, lottery):
            await interaction.response.send_message('❌ 只有建立者可以開始抽獎。', ephemeral=True); return

        participants = lottery['participants']
        winner_count = lottery['winner_count']
        if not participants:
            await interaction.response.send_message('❌ 尚未加入任何參加成員！', ephemeral=True); return
        if len(participants) < winner_count:
            await interaction.response.send_message(
                f'❌ 參加人數（{len(participants)}）少於中獎人數（{winner_count}）。',
                ephemeral=True); return

        storage = _load_storage()
        if not storage:
            await interaction.response.send_message('❌ 儲存庫目前沒有物品可抽！', ephemeral=True); return

        await interaction.response.send_message('🎲 正在抽獎中…', ephemeral=True)

        countdown_embed = discord.Embed(
            title=f'🎰 捐獻抽獎即將開始：{lottery["name"]}', color=0xFF6B6B)
        msg = await interaction.channel.send(embed=countdown_embed)
        for i in [3, 2, 1]:
            countdown_embed.description = f'# {i}'
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        winners = random.sample(participants, min(winner_count, len(participants)))
        pool    = list(storage)
        random.shuffle(pool)
        pairs   = [(w, pool[i % len(pool)]) for i, w in enumerate(winners)]
        used_ids = {item['id'] for _, item in pairs}
        _save_storage([it for it in storage if it['id'] not in used_ids])

        active_donation_lotteries.pop(interaction.guild_id, None)
        donation_scheduled_tasks.pop(interaction.guild_id, None)
        _save_lotteries()

        result_embed = discord.Embed(
            title=f'🏆 捐獻抽獎結果：{lottery["name"]}',
            color=0x00FF88, timestamp=tw_now())
        for winner, item in pairs:
            det = item.get('details', {})
            if item['type'] == '裝備':
                extra = f"\n強化：{det.get('enhancement','—')} | 潛能：{det.get('potential','—')}"
            else:
                extra = f"\n數量：{det.get('quantity','?')}"
            result_embed.add_field(
                name=f'🏆 {winner["name"]}',
                value=f'{ICON.get(item["type"],"📦")} **{item["name"]}**{extra}',
                inline=False,
            )
        result_embed.set_footer(text=f'由 {interaction.user.display_name} 主持 | 物品已從儲存庫移除')
        await msg.edit(embed=result_embed)
        await interaction.channel.send('🎉 恭喜！' + ' '.join(f'<@{w["id"]}>' for w, _ in pairs))

    # ── 查看名單 ──────────────────────────────────────────────────
    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.secondary,
               custom_id='donation_lottery_view_list', row=3)
    async def view_list_btn(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery(interaction)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True); return
        if not lottery['participants']:
            await interaction.response.send_message('📭 目前無加入成員。', ephemeral=True); return
        embed = discord.Embed(
            title=f'📋 {lottery["name"]} — 參加名單',
            description='\n'.join(
                f'│`{i+1:>2}.` {p["name"]}' for i, p in enumerate(lottery['participants'])
            )[:4096],
            color=0x5865F2,
        )
        embed.set_footer(text=f'共 {len(lottery["participants"])} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 查看儲存庫 ────────────────────────────────────────────────
    @ui.button(label='📦 查看儲存庫', style=discord.ButtonStyle.secondary,
               custom_id='donation_lottery_view_storage', row=3)
    async def view_storage_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.client.db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可查看儲存庫。', ephemeral=True)
            return
        storage = _load_storage()
        if not storage:
            await interaction.response.send_message('📭 儲存庫目前沒有任何物品。', ephemeral=True)
            return
        lines = [f'**📦 公會儲存庫（共 {len(storage)} 件）**\n']
        for item in storage:
            det  = item.get('details', {})
            free = '🆓' if item.get('is_free') else '💰'
            if item['type'] == '裝備':
                extra = f" | {det.get('enhancement','—')} | {det.get('potential','—')}"
            else:
                extra = f" ×{det.get('quantity','?')}"
            lines.append(
                f'`{item["id"]}` {ICON.get(item["type"],"📦")}{free} **{item["name"]}**{extra}\n'
                f'　　捐獻者：{item["donor"]} | 入庫：{item.get("received_at","")[:10]}'
            )
        text = '\n'.join(lines)
        await interaction.response.send_message(text[:1990] + ('…' if len(text) > 1990 else ''),
                                                 ephemeral=True)

    # ── 清空名單 ──────────────────────────────────────────────────
    @ui.button(label='🗑️ 清空名單', style=discord.ButtonStyle.danger,
               custom_id='donation_lottery_clear', row=4)
    async def clear_btn(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery(interaction)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True); return
        if not self._is_creator(interaction, lottery):
            await interaction.response.send_message('❌ 只有建立者可以清空名單。', ephemeral=True); return
        lottery['participants'] = []
        _save_lotteries()
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if '已指定成員' in field.name:
                embed.set_field_at(i, name='👥 已指定成員（共 0 人）',
                                   value='尚未加入任何成員', inline=False)
                break
        await interaction.response.edit_message(embed=embed)

    # ── 取消抽獎 ──────────────────────────────────────────────────
    @ui.button(label='✖ 取消抽獎', style=discord.ButtonStyle.secondary,
               custom_id='donation_lottery_cancel', row=4)
    async def cancel_btn(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery(interaction)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽獎活動。', ephemeral=True); return
        if not self._is_creator(interaction, lottery):
            await interaction.response.send_message('❌ 只有建立者可以取消。', ephemeral=True); return
        active_donation_lotteries.pop(interaction.guild_id, None)
        donation_scheduled_tasks.pop(interaction.guild_id, None)
        _save_lotteries()
        embed = discord.Embed(
            title='✖ 捐獻抽獎已取消',
            description=f'「{lottery["name"]}」已被 {interaction.user.display_name} 取消。',
            color=0xFF0000,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── 建立捐獻抽獎表單 ──────────────────────────────────────────────

class DonationLotteryModal(ui.Modal, title='🎰 建立捐獻抽獎'):
    lottery_name  = ui.TextInput(label='抽獎名稱', placeholder='例如：本週捐獻回饋抽獎',
                                 required=True, max_length=50)
    winner_count  = ui.TextInput(label='中獎人數', placeholder='例如：3',
                                 required=True, max_length=3)
    schedule_time = ui.TextInput(
        label='定時開獎（台灣時間，選填）',
        placeholder='格式：2026-05-10 20:00（留空＝手動開獎）',
        required=False, max_length=20,
    )
    notes = ui.TextInput(
        label='活動說明（選填）',
        style=discord.TextStyle.paragraph,
        placeholder='填寫額外說明…',
        required=False, max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.winner_count.value)
            if count < 1: raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 中獎人數必須是正整數！', ephemeral=True)
            return

        draw_time = None
        if self.schedule_time.value.strip():
            try:
                draw_time = datetime.strptime(
                    self.schedule_time.value.strip(), '%Y-%m-%d %H:%M'
                ).replace(tzinfo=TW_TZ)
                if draw_time <= tw_now():
                    await interaction.response.send_message(
                        '❌ 定時時間必須是未來的時間！', ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message(
                    '❌ 時間格式錯誤，請用：`2026-05-10 20:00`', ephemeral=True)
                return

        storage = _load_storage()
        if not storage:
            await interaction.response.send_message(
                '❌ 儲存庫目前沒有物品，無法建立抽獎。', ephemeral=True)
            return

        gid = interaction.guild_id
        if gid in active_donation_lotteries:
            await interaction.response.send_message(
                '⚠️ 目前已有一個進行中的捐獻抽獎，請先結束再開新的。', ephemeral=True)
            return

        time_str = draw_time.strftime('%Y-%m-%d %H:%M') if draw_time else '手動開獎'
        active_donation_lotteries[gid] = {
            'name':         self.lottery_name.value,
            'winner_count': count,
            'notes':        self.notes.value or '',
            'participants': [],
            'creator':      interaction.user.id,
            'created_at':   tw_now(),
            'draw_time':    draw_time,
            'channel_id':   interaction.channel_id,
        }
        if draw_time:
            donation_scheduled_tasks[gid] = {
                'guild_id':   gid,
                'channel_id': interaction.channel_id,
                'draw_time':  draw_time,
            }
        _save_lotteries()

        embed = discord.Embed(
            title=f'🎰 捐獻抽獎：{self.lottery_name.value}',
            description='📋 以下為抽獎資訊，僅建立者可操作下方按鈕。',
            color=0xFFD700,
        )
        embed.add_field(name='🎁 獎品',
                        value=f'從儲存庫隨機抽取（共 {len(storage)} 件）', inline=True)
        embed.add_field(name='🥇 中獎人數', value=f'{count} 人',  inline=True)
        embed.add_field(name='⏰ 開獎時間', value=time_str,        inline=True)
        if self.notes.value:
            embed.add_field(name='📝 說明', value=self.notes.value, inline=False)
        embed.add_field(name='👥 已指定成員（共 0 人）', value='尚未加入任何成員', inline=False)
        embed.set_footer(text=f'建立者：{interaction.user.display_name}｜僅建立者可操作')

        await interaction.response.send_message(
            embed=embed, view=DonationLotteryManageView())


# ── Cog ──────────────────────────────────────────────────────────

class DonationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load_lotteries()
        bot.add_view(DonationPanelView())
        bot.add_view(DonationAcceptView())
        bot.add_view(DonationLotteryManageView())
        self.expire_check.start()
        self.lottery_check.start()

    def cog_unload(self):
        self.expire_check.cancel()
        self.lottery_check.cancel()

    # ── 過期捐獻清理 ──────────────────────────────────────────────
    @tasks.loop(minutes=15)
    async def expire_check(self):
        pending = _load_pending()
        now     = tw_now()
        expired = []
        for mid, d in list(pending.items()):
            try:
                created = datetime.fromisoformat(d['created_at'])
                if (now - created) > timedelta(hours=EXPIRE_HOURS):
                    expired.append((mid, d))
            except Exception:
                expired.append((mid, d))

        for mid, d in expired:
            del pending[mid]
            try:
                guild = self.bot.get_guild(int(d['guild_id']))
                ch    = guild.get_channel(int(d['channel_id']))
                msg   = await ch.fetch_message(int(mid))
                embed = msg.embeds[0]
                embed.color = 0x95A5A6
                embed.title = f'[已失效] {embed.title}'
                embed.set_footer(text='⏰ 超過 6 小時未被接收，已自動失效')
                await msg.edit(embed=embed, view=None)
            except Exception:
                pass

        if expired:
            _save_pending(pending)

    @expire_check.before_loop
    async def before_expire(self):
        await self.bot.wait_until_ready()

    # ── 定時抽獎檢查 ──────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def lottery_check(self):
        now = tw_now()
        for gid, task in list(donation_scheduled_tasks.items()):
            if now < task['draw_time']:
                continue

            lottery = active_donation_lotteries.get(gid)
            donation_scheduled_tasks.pop(gid, None)
            if not lottery:
                _save_lotteries()
                continue

            channel = self.bot.get_channel(task['channel_id'])
            if not channel:
                active_donation_lotteries.pop(gid, None)
                _save_lotteries()
                continue

            participants = lottery['participants']
            winner_count = lottery['winner_count']
            if len(participants) < winner_count:
                await channel.send(
                    f'❌ 定時捐獻抽獎「{lottery["name"]}」參加人數不足（{len(participants)}/{winner_count}），已取消。'
                )
                active_donation_lotteries.pop(gid, None)
                _save_lotteries()
                continue

            storage = _load_storage()
            if not storage:
                await channel.send(f'❌ 定時抽獎「{lottery["name"]}」儲存庫沒有物品，已取消。')
                active_donation_lotteries.pop(gid, None)
                _save_lotteries()
                continue

            countdown_embed = discord.Embed(
                title=f'⏰ 定時捐獻抽獎開始：{lottery["name"]}', color=0xFF6B6B)
            msg = await channel.send(embed=countdown_embed)
            for i in [3, 2, 1]:
                countdown_embed.description = f'# {i}'
                await msg.edit(embed=countdown_embed)
                await asyncio.sleep(1)

            winners = random.sample(participants, min(winner_count, len(participants)))
            pool    = list(storage)
            random.shuffle(pool)
            pairs   = [(w, pool[i % len(pool)]) for i, w in enumerate(winners)]
            used_ids = {item['id'] for _, item in pairs}
            _save_storage([it for it in storage if it['id'] not in used_ids])
            active_donation_lotteries.pop(gid, None)
            _save_lotteries()

            result_embed = discord.Embed(
                title=f'🏆 定時捐獻抽獎結果：{lottery["name"]}',
                color=0x00FF88, timestamp=tw_now())
            for winner, item in pairs:
                det = item.get('details', {})
                extra = (f"\n強化：{det.get('enhancement','—')} | 潛能：{det.get('potential','—')}"
                         if item['type'] == '裝備' else f"\n數量：{det.get('quantity','?')}")
                result_embed.add_field(
                    name=f'🏆 {winner["name"]}',
                    value=f'{ICON.get(item["type"],"📦")} **{item["name"]}**{extra}',
                    inline=False,
                )
            result_embed.set_footer(text='⏰ 定時自動抽獎 | 物品已從儲存庫移除')
            await msg.edit(embed=result_embed)
            await channel.send('🎉 恭喜！' + ' '.join(f'<@{w["id"]}>' for w, _ in pairs))

    @lottery_check.before_loop
    async def before_lottery_check(self):
        await self.bot.wait_until_ready()

    # ── /設定捐獻頻道 ────────────────────────────────────────────
    @app_commands.command(name='設定捐獻頻道', description='設定捐獻通知要發送的頻道')
    @app_commands.describe(頻道='捐獻通知將出現在此頻道')
    @admin_only()
    async def set_donation_ch(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['donation_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 捐獻通知頻道已設定為 {頻道.mention}', ephemeral=True)

    # ── /捐獻面板 ────────────────────────────────────────────────
    @app_commands.command(name='捐獻面板', description='在此頻道發布捐獻面板（僅限管理員）')
    @admin_only()
    async def donation_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='🎁 公會捐獻系統',
            description=(
                '有多餘的裝備、卷軸或物品想捐獻給公會嗎？\n'
                '點擊下方按鈕即可開始捐獻，管理員審核後自動入庫！\n\n'
                '**可捐獻類型：**\n'
                '⚔️ 裝備（填寫強化、潛能等詳細資料）\n'
                '📜 卷軸（填寫名稱與數量）\n'
                '📦 其他物品（填寫名稱與數量）'
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, view=DonationPanelView())

    # ── /查詢儲存庫 ──────────────────────────────────────────────
    @app_commands.command(name='查詢儲存庫', description='查看公會儲存庫的所有物品（僅限管理員）')
    @admin_only()
    async def query_storage(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        storage = _load_storage()
        if not storage:
            await interaction.followup.send('📭 儲存庫目前沒有任何物品。', ephemeral=True)
            return

        lines = [f'**📦 公會儲存庫（共 {len(storage)} 件）**\n']
        for item in storage:
            det  = item.get('details', {})
            free = '🆓' if item.get('is_free') else '💰'
            if item['type'] == '裝備':
                extra = f" | {det.get('enhancement','—')} | {det.get('potential','—')}"
            else:
                extra = f" ×{det.get('quantity','?')}"
            date = item.get('received_at', '')[:10]
            lines.append(
                f'`{item["id"]}` {ICON.get(item["type"],"📦")}{free} **{item["name"]}**{extra}\n'
                f'　　捐獻者：{item["donor"]} | 入庫：{date}'
            )

        text = '\n'.join(lines)
        if len(text) <= 1900:
            await interaction.followup.send(text, ephemeral=True)
        else:
            chunks, cur = [], lines[0]
            for line in lines[1:]:
                if len(cur) + len(line) + 1 > 1900:
                    chunks.append(cur)
                    cur = line
                else:
                    cur += '\n' + line
            chunks.append(cur)
            for chunk in chunks:
                await interaction.followup.send(chunk, ephemeral=True)

    # ── /刪除儲存庫物品 ──────────────────────────────────────────
    @app_commands.command(name='刪除儲存庫物品', description='從儲存庫刪除指定物品（輸入物品 ID）')
    @app_commands.describe(物品id='8 位物品 ID（用 /查詢儲存庫 查看）')
    @admin_only()
    async def delete_storage_item(self, interaction: discord.Interaction, 物品id: str):
        storage  = _load_storage()
        filtered = [i for i in storage if i['id'].upper() != 物品id.strip().upper()]
        if len(filtered) == len(storage):
            await interaction.response.send_message(
                f'❌ 找不到 ID 為 `{物品id}` 的物品。', ephemeral=True)
            return
        _save_storage(filtered)
        await interaction.response.send_message(
            f'✅ 已從儲存庫刪除 ID `{物品id.upper()}` 的物品。', ephemeral=True)

    # ── /捐獻抽獎 ────────────────────────────────────────────────
    @app_commands.command(name='捐獻抽獎', description='建立捐獻抽獎，從儲存庫隨機抽出物品（僅限管理員）')
    @admin_only()
    async def donation_lottery_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DonationLotteryModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(DonationCog(bot))
