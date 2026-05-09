import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timedelta, timezone

from utils.database import _load, _save
from utils.helpers import admin_only

TW_TZ = timezone(timedelta(hours=8))

def tw_now() -> datetime:
    return datetime.now(TW_TZ)

active_parties: dict[str, dict] = {}
PARTY_FILE = 'parties.json'


def _load_parties():
    global active_parties
    active_parties = _load(PARTY_FILE)

def _save_parties():
    _save(PARTY_FILE, active_parties)

def _bar(joined: int, total: int) -> str:
    return '█' * joined + '░' * (total - joined)

def _rebuild_embed(party: dict) -> discord.Embed:
    joined = len(party['members'])
    total  = party['slots_needed']
    closed = party.get('closed', False)

    embed = discord.Embed(
        title = f'🎯 組隊任務：{party["task_name"]}',
        color = 0x95A5A6 if closed else 0x1ABC9C,
        timestamp = tw_now(),
    )
    embed.add_field(name='📋 等級限制', value=party['level_req'],           inline=True)
    embed.add_field(name='⏰ 開始時間', value=party['start_time'],          inline=True)
    embed.add_field(name='👑 發起人',   value=f'<@{party["leader_id"]}>',  inline=True)
    embed.add_field(
        name  = '👥 已加入',
        value = f'{joined} / {total} 人\n`{_bar(joined, total)}`',
        inline = True,
    )

    if party['members']:
        names = '\n'.join(
            f'`{i+1}.` {m["display_name"]}'
            for i, m in enumerate(party['members'])
        )
        embed.add_field(name='📋 成員名單', value=names[:1024], inline=False)

    if closed:
        embed.set_footer(text='🔒 此組隊已關閉')
    else:
        embed.set_footer(text='點擊「✅ 申請加入」即可一鍵加入 | 名額有限先搶先得')
    return embed


# ── 移除成員選單（ephemeral，僅隊長）───────────────────────────────

class PartyRemoveSelect(ui.Select):
    def __init__(self, message_id: str, party: dict):
        self.message_id = message_id
        options = [
            discord.SelectOption(
                label = m['display_name'][:100],
                value = m['user_id'],
            )
            for m in party['members'][:25]
        ]
        super().__init__(placeholder='選擇要移除的成員…',
                         options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        party = active_parties.get(self.message_id)
        if not party:
            await interaction.response.send_message('❌ 組隊不存在。', ephemeral=True)
            return
        if str(interaction.user.id) != str(party['leader_id']):
            await interaction.response.send_message('❌ 只有發起人可以移除成員。', ephemeral=True)
            return

        target_id = self.values[0]
        removed   = next((m for m in party['members'] if m['user_id'] == target_id), None)
        if not removed:
            await interaction.response.send_message('❌ 找不到該成員。', ephemeral=True)
            return

        party['members'] = [m for m in party['members'] if m['user_id'] != target_id]
        _save_parties()

        try:
            ch  = interaction.client.get_channel(int(party['channel_id']))
            msg = await ch.fetch_message(int(self.message_id))
            await msg.edit(embed=_rebuild_embed(party))
        except Exception:
            pass

        await interaction.response.send_message(
            f'✅ 已移除 **{removed["display_name"]}**。', ephemeral=True)


class PartyRemoveView(ui.View):
    def __init__(self, message_id: str, party: dict):
        super().__init__(timeout=60)
        self.add_item(PartyRemoveSelect(message_id, party))


# ── 組隊文章按鈕（持久化）────────────────────────────────────────

class PartyJoinView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ── ✅ 申請加入（一鍵加入，無需填表）────────────────────────
    @ui.button(label='✅ 申請加入', style=discord.ButtonStyle.success,
               custom_id='party_join', row=0)
    async def join_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid   = str(interaction.message.id)
        party = active_parties.get(mid)
        if not party:
            await interaction.response.send_message('❌ 此組隊已結束或不存在。', ephemeral=True)
            return
        if party.get('closed'):
            await interaction.response.send_message('❌ 此組隊已關閉。', ephemeral=True)
            return

        uid = str(interaction.user.id)

        # 已加入
        if any(m['user_id'] == uid for m in party['members']):
            await interaction.response.send_message('⚠️ 你已在此組隊中！', ephemeral=True)
            return

        # 名額已滿
        if len(party['members']) >= party['slots_needed']:
            await interaction.response.send_message('❌ 名額已滿，無法加入。', ephemeral=True)
            return

        # 加入
        party['members'].append({
            'user_id':      uid,
            'discord':      str(interaction.user),
            'display_name': interaction.user.display_name,
            'joined_at':    tw_now().isoformat(),
        })
        _save_parties()

        await interaction.response.edit_message(embed=_rebuild_embed(party))
        await interaction.followup.send('✅ 已成功加入組隊！', ephemeral=True)

        # 通知發起人
        try:
            leader = interaction.guild.get_member(int(party['leader_id']))
            if leader:
                joined = len(party['members'])
                total  = party['slots_needed']
                dm = discord.Embed(
                    title       = f'📩 有人加入你的組隊！',
                    description = f'**任務：** {party["task_name"]}',
                    color       = 0x1ABC9C,
                    timestamp   = tw_now(),
                )
                dm.add_field(name='新加入成員', value=interaction.user.mention, inline=True)
                dm.add_field(name='目前人數',   value=f'{joined} / {total} 人',  inline=True)
                if joined >= total:
                    dm.add_field(name='🎉 狀態', value='**名額已滿！**', inline=False)
                await leader.send(embed=dm)
        except Exception:
            pass

    # ── 📋 查看名單（隊長看完整，其他人看人數）──────────────────
    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.primary,
               custom_id='party_list', row=0)
    async def list_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid   = str(interaction.message.id)
        party = active_parties.get(mid)
        if not party:
            await interaction.response.send_message('❌ 此組隊已結束。', ephemeral=True)
            return

        joined = len(party['members'])
        total  = party['slots_needed']

        if str(interaction.user.id) != str(party['leader_id']):
            await interaction.response.send_message(
                f'👥 目前已加入：**{joined} / {total}** 人', ephemeral=True)
            return

        if not party['members']:
            await interaction.response.send_message('📭 目前尚無成員加入。', ephemeral=True)
            return

        embed = discord.Embed(
            title  = f'📋 {party["task_name"]} — 成員名單',
            color  = 0x1ABC9C,
        )
        for i, m in enumerate(party['members'], 1):
            embed.add_field(
                name  = f'{i}. {m["display_name"]}',
                value = f'<@{m["user_id"]}>',
                inline = True,
            )
        embed.set_footer(text=f'{joined} / {total} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 🗑️ 移除成員（僅隊長）───────────────────────────────────
    @ui.button(label='🗑️ 移除成員', style=discord.ButtonStyle.secondary,
               custom_id='party_remove', row=1)
    async def remove_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid   = str(interaction.message.id)
        party = active_parties.get(mid)
        if not party:
            await interaction.response.send_message('❌ 此組隊已結束。', ephemeral=True)
            return
        if str(interaction.user.id) != str(party['leader_id']):
            await interaction.response.send_message('❌ 只有發起人可以移除成員。', ephemeral=True)
            return
        if not party['members']:
            await interaction.response.send_message('📭 目前尚無成員可移除。', ephemeral=True)
            return
        await interaction.response.send_message(
            f'請選擇要移除的成員（共 {len(party["members"])} 人）：',
            view=PartyRemoveView(mid, party), ephemeral=True)

    # ── 🔒 關閉組隊（僅隊長）───────────────────────────────────
    @ui.button(label='🔒 關閉組隊', style=discord.ButtonStyle.danger,
               custom_id='party_close', row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid   = str(interaction.message.id)
        party = active_parties.get(mid)
        if not party:
            await interaction.response.send_message('❌ 此組隊已結束。', ephemeral=True)
            return
        if str(interaction.user.id) != str(party['leader_id']):
            await interaction.response.send_message('❌ 只有發起人可以關閉組隊。', ephemeral=True)
            return

        party['closed'] = True
        active_parties.pop(mid, None)
        _save_parties()

        embed = _rebuild_embed({**party, 'closed': True})
        await interaction.response.edit_message(embed=embed, view=None)


# ── 建立組隊表單 ──────────────────────────────────────────────────

class PartyCreateModal(ui.Modal, title='🎯 建立組隊任務'):
    task_name   = ui.TextInput(label='組隊任務名稱',
                               placeholder='例如：超綠',
                               required=True, max_length=50)
    level_req   = ui.TextInput(label='等級限制',
                               placeholder='例如：120 級以上  /  無限制',
                               required=True, max_length=30)
    start_time  = ui.TextInput(label='開始時間',
                               placeholder='例如：今晚 21:00  /  5/10 20:30 / 人滿開始',
                               required=True, max_length=50)
    slots_needed = ui.TextInput(label='缺少人數',
                                placeholder='例如：5（還缺 5 人）',
                                required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            slots = int(self.slots_needed.value)
            if slots < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 缺少人數必須是正整數！', ephemeral=True)
            return

        gs      = interaction.client.db.get_guild_settings(interaction.guild_id)
        ch_id   = gs.get('party_channel')
        if not ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定組隊頻道！請管理員先使用 `/設定組隊頻道` 設定。', ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message('❌ 找不到組隊頻道，請重新設定。', ephemeral=True)
            return

        party = {
            'task_name':   self.task_name.value,
            'level_req':   self.level_req.value,
            'start_time':  self.start_time.value,
            'slots_needed': slots,
            'leader_id':   str(interaction.user.id),
            'channel_id':  str(channel.id),
            'guild_id':    str(interaction.guild_id),
            'members':     [],
            'closed':      False,
            'created_at':  tw_now().isoformat(),
        }

        msg = await channel.send(embed=_rebuild_embed(party), view=PartyJoinView())
        active_parties[str(msg.id)] = party
        _save_parties()

        await interaction.response.send_message(
            f'✅ 組隊任務已發布至 {channel.mention}！', ephemeral=True)


# ── 主控面板（持久化）────────────────────────────────────────────

class PartyPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🎯 建立組隊任務', style=discord.ButtonStyle.success,
               custom_id='party_create_btn', row=0)
    async def create_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PartyCreateModal())


# ── Cog ──────────────────────────────────────────────────────────

class PartyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load_parties()
        bot.add_view(PartyJoinView())
        bot.add_view(PartyPanelView())

    # ── /組隊面板 ────────────────────────────────────────────────
    @app_commands.command(name='組隊面板', description='🎯 在此頻道發布組隊任務面板（僅限管理員）')
    @admin_only()
    async def party_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '🎯 組隊任務系統',
            description = (
                '想找人一起完成任務？點擊下方按鈕建立組隊！\n\n'
                '**流程：**\n'
                '1️⃣ 點擊「建立組隊任務」填寫表單\n'
                '2️⃣ 機器人自動在組隊頻道發布公告\n'
                '3️⃣ 玩家點擊「✅ 申請加入」一鍵入隊\n'
                '4️⃣ 人滿或結束後點「🔒 關閉組隊」'
            ),
            color = 0x1ABC9C,
        )
        await interaction.response.send_message(embed=embed, view=PartyPanelView())

    # ── /設定組隊頻道 ────────────────────────────────────────────
    @app_commands.command(name='設定組隊頻道', description='設定組隊任務公告要發布的頻道（僅限管理員）')
    @app_commands.describe(頻道='組隊公告將發布到此頻道')
    @admin_only()
    async def set_party_ch(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['party_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 組隊頻道已設定為 {頻道.mention}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PartyCog(bot))
