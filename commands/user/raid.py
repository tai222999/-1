import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timedelta, timezone

from utils.database import _load, _save
from utils.helpers import admin_only

TW_TZ = timezone(timedelta(hours=8))

def tw_now() -> datetime:
    return datetime.now(TW_TZ)

# 進行中的遠征隊：{str(message_id): raid_data}
active_raids: dict[str, dict] = {}
RAID_FILE = 'raids.json'


def _load_raids():
    global active_raids
    active_raids = _load(RAID_FILE)

def _save_raids():
    _save(RAID_FILE, active_raids)


# ── 申請加入表單 ──────────────────────────────────────────────────

class RaidApplyModal(ui.Modal, title='✋ 申請加入遠征隊'):
    char_name  = ui.TextInput(label='角色名稱',   placeholder='你的遊戲角色名稱',   required=True,  max_length=50)
    char_class = ui.TextInput(label='職業',       placeholder='例如：黑騎士',       required=True,  max_length=30)
    char_level = ui.TextInput(label='等級',       placeholder='例如：120',         required=True,  max_length=10)
    char_atk   = ui.TextInput(label='表攻',       placeholder='例如：20000',        required=True,  max_length=20)
    note       = ui.TextInput(label='備註（選填）', placeholder='其他想告知隊長的事', required=False, max_length=200)

    def __init__(self, message_id: str):
        super().__init__()
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        raid = active_raids.get(self.message_id)
        if not raid:
            await interaction.response.send_message('❌ 此招募已結束或不存在。', ephemeral=True)
            return

        # 防重複報名
        if any(str(a['user_id']) == str(interaction.user.id) for a in raid['applicants']):
            await interaction.response.send_message('⚠️ 你已經申請過了！', ephemeral=True)
            return

        # 名額已滿
        if len(raid['applicants']) >= raid['max_members']:
            await interaction.response.send_message('❌ 名額已滿，無法報名。', ephemeral=True)
            return

        applicant = {
            'user_id':    str(interaction.user.id),
            'discord':    str(interaction.user),
            'char_name':  self.char_name.value,
            'char_class': self.char_class.value,
            'char_level': self.char_level.value,
            'char_atk':   self.char_atk.value,
            'note':       self.note.value or '',
            'applied_at': tw_now().isoformat(),
        }
        raid['applicants'].append(applicant)
        _save_raids()

        # 更新 Embed 的「目前報名」欄位
        try:
            ch  = interaction.client.get_channel(int(raid['channel_id']))
            msg = await ch.fetch_message(int(self.message_id))
            embed = msg.embeds[0]
            for i, field in enumerate(embed.fields):
                if '目前報名' in field.name:
                    filled = len(raid['applicants'])
                    total  = raid['max_members']
                    bar    = '█' * filled + '░' * (total - filled)
                    embed.set_field_at(
                        i,
                        name='👥 目前報名',
                        value=f'{filled} / {total} 人\n`{bar}`',
                        inline=True,
                    )
                    break
            await msg.edit(embed=embed)
        except Exception:
            pass

        # ① 申請人看到（ephemeral = 只有自己看得到）
        confirm_embed = discord.Embed(
            title='✅ 申請已送出！',
            description='以下是你的報名資料，隊長已收到通知。',
            color=0x2ECC71,
        )
        confirm_embed.add_field(name='遠征隊', value=raid['boss'],          inline=True)
        confirm_embed.add_field(name='角色名稱', value=self.char_name.value, inline=True)
        confirm_embed.add_field(name='職業',    value=self.char_class.value, inline=True)
        confirm_embed.add_field(name='等級',    value=self.char_level.value, inline=True)
        confirm_embed.add_field(name='表攻',    value=self.char_atk.value,   inline=True)
        if self.note.value:
            confirm_embed.add_field(name='備註', value=self.note.value, inline=False)
        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)

        # ② 通知隊長（DM，只有隊長看得到）
        try:
            leader = interaction.guild.get_member(int(raid['leader_id']))
            if leader:
                dm_embed = discord.Embed(
                    title=f'📩 有人申請加入你的遠征隊！',
                    description=f'**遠征隊：** {raid["boss"]}',
                    color=0x3498DB,
                    timestamp=tw_now(),
                )
                dm_embed.add_field(name='Discord',  value=f'{interaction.user.mention}', inline=True)
                dm_embed.add_field(name='角色名稱', value=self.char_name.value,           inline=True)
                dm_embed.add_field(name='職業',    value=self.char_class.value,           inline=True)
                dm_embed.add_field(name='等級',    value=self.char_level.value,           inline=True)
                dm_embed.add_field(name='表攻',    value=self.char_atk.value,             inline=True)
                if self.note.value:
                    dm_embed.add_field(name='備註', value=self.note.value, inline=False)
                dm_embed.set_footer(text=f'目前報名：{len(raid["applicants"])} / {raid["max_members"]} 人')
                await leader.send(embed=dm_embed)
        except Exception:
            pass


# ── 移除成員下拉選單（ephemeral，僅隊長可見）─────────────────────

class RaidRemoveSelect(ui.Select):
    def __init__(self, message_id: str, raid: dict):
        self.message_id = message_id
        options = [
            discord.SelectOption(
                label=f"{a['char_name']}（{a['char_class']}）"[:100],
                description=f"Lv.{a['char_level']} 表攻:{a['char_atk']}",
                value=str(a['user_id']),
            )
            for a in raid['applicants'][:25]
        ]
        super().__init__(placeholder='選擇要移除的成員…', options=options,
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        raid = active_raids.get(self.message_id)
        if not raid:
            await interaction.response.send_message('❌ 招募不存在。', ephemeral=True)
            return
        if str(interaction.user.id) != str(raid['leader_id']):
            await interaction.response.send_message('❌ 只有隊長可以移除成員。', ephemeral=True)
            return

        target_id = self.values[0]
        removed = next((a for a in raid['applicants'] if str(a['user_id']) == target_id), None)
        if not removed:
            await interaction.response.send_message('❌ 找不到該成員。', ephemeral=True)
            return

        raid['applicants'] = [a for a in raid['applicants'] if str(a['user_id']) != target_id]
        _save_raids()

        try:
            ch  = interaction.client.get_channel(int(raid['channel_id']))
            msg = await ch.fetch_message(int(self.message_id))
            embed = msg.embeds[0]
            for i, field in enumerate(embed.fields):
                if '目前報名' in field.name:
                    filled = len(raid['applicants'])
                    total  = raid['max_members']
                    bar    = '█' * filled + '░' * (total - filled)
                    embed.set_field_at(i, name='👥 目前報名',
                                       value=f'{filled} / {total} 人\n`{bar}`', inline=True)
                    break
            await msg.edit(embed=embed)
        except Exception:
            pass

        await interaction.response.send_message(
            f'✅ 已移除 **{removed["char_name"]}**（{removed["discord"]}）的報名。',
            ephemeral=True,
        )


class RaidManageView(ui.View):
    def __init__(self, message_id: str, raid: dict):
        super().__init__(timeout=60)
        self.add_item(RaidRemoveSelect(message_id, raid))


# ── 遠征隊公告上的按鈕面板（公開，持久化）────────────────────────

class RaidJoinView(ui.View):
    """timeout=None + 固定 custom_id → 重啟後按鈕仍有效。"""

    def __init__(self):
        super().__init__(timeout=None)

    # ── ✋ 申請加入 ────────────────────────────────────────────
    @ui.button(label='✋ 申請加入', style=discord.ButtonStyle.success,
               custom_id='raid_apply', row=0)
    async def apply_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid  = str(interaction.message.id)
        raid = active_raids.get(mid)
        if not raid:
            await interaction.response.send_message('❌ 此招募已結束或不存在。', ephemeral=True)
            return
        if len(raid['applicants']) >= raid['max_members']:
            await interaction.response.send_message('❌ 名額已滿！', ephemeral=True)
            return
        if any(str(a['user_id']) == str(interaction.user.id) for a in raid['applicants']):
            # 已報名 → 顯示自己的資料
            a = next(x for x in raid['applicants'] if str(x['user_id']) == str(interaction.user.id))
            e = discord.Embed(title='📋 你的報名資料', color=0x3498DB)
            e.add_field(name='角色名稱', value=a['char_name'],  inline=True)
            e.add_field(name='職業',    value=a['char_class'],  inline=True)
            e.add_field(name='等級',    value=a['char_level'],  inline=True)
            e.add_field(name='表攻',    value=a['char_atk'],    inline=True)
            if a.get('note'):
                e.add_field(name='備註', value=a['note'], inline=False)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        await interaction.response.send_modal(RaidApplyModal(mid))

    # ── 📋 查看名單（隊長看全部，其他人看人數）──────────────────
    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.primary,
               custom_id='raid_list', row=0)
    async def list_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid  = str(interaction.message.id)
        raid = active_raids.get(mid)
        if not raid:
            await interaction.response.send_message('❌ 此招募已結束。', ephemeral=True)
            return

        filled = len(raid['applicants'])
        total  = raid['max_members']

        # 非隊長只看人數
        if str(interaction.user.id) != str(raid['leader_id']):
            await interaction.response.send_message(
                f'👥 目前報名人數：**{filled} / {total}** 人',
                ephemeral=True
            )
            return

        # 隊長看完整名單（ephemeral，只有隊長看得到）
        if not raid['applicants']:
            await interaction.response.send_message('📭 目前沒有人報名。', ephemeral=True)
            return

        embed = discord.Embed(
            title=f'📋 {raid["boss"]} — 報名名單',
            color=0x5865F2,
        )
        for i, a in enumerate(raid['applicants'], 1):
            note_str = f'\n備註：{a["note"]}' if a.get('note') else ''
            embed.add_field(
                name=f'{i}. {a["char_name"]}（{a["char_class"]}）',
                value=f'等級：{a["char_level"]}　表攻：{a["char_atk"]}{note_str}\n<@{a["user_id"]}>',
                inline=False,
            )
        embed.set_footer(text=f'{filled} / {total} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 🗑️ 移除成員（僅隊長）────────────────────────────────────
    @ui.button(label='🗑️ 移除成員', style=discord.ButtonStyle.secondary,
               custom_id='raid_remove', row=1)
    async def remove_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid  = str(interaction.message.id)
        raid = active_raids.get(mid)
        if not raid:
            await interaction.response.send_message('❌ 此招募已結束。', ephemeral=True)
            return
        if str(interaction.user.id) != str(raid['leader_id']):
            await interaction.response.send_message('❌ 只有隊長可以移除成員。', ephemeral=True)
            return
        if not raid['applicants']:
            await interaction.response.send_message('📭 目前沒有報名者。', ephemeral=True)
            return

        view = RaidManageView(mid, raid)
        await interaction.response.send_message(
            f'請選擇要移除的成員（共 {len(raid["applicants"])} 人）：',
            view=view,
            ephemeral=True,
        )

    # ── 🔒 關閉招募（僅隊長）─────────────────────────────────
    @ui.button(label='🔒 關閉招募', style=discord.ButtonStyle.danger,
               custom_id='raid_close', row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        mid  = str(interaction.message.id)
        raid = active_raids.get(mid)
        if not raid:
            await interaction.response.send_message('❌ 此招募已結束。', ephemeral=True)
            return
        if str(interaction.user.id) != str(raid['leader_id']):
            await interaction.response.send_message('❌ 只有隊長可以關閉招募。', ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        embed.color = 0x95A5A6
        embed.title = f'[已關閉] {embed.title}'
        embed.set_footer(text='此招募已由隊長關閉')

        active_raids.pop(mid, None)
        _save_raids()

        await interaction.response.edit_message(embed=embed, view=None)


# ── 建立招募表單 ──────────────────────────────────────────────────

class RaidCreateModal(ui.Modal, title='⚔️ 建立遠征隊招募'):
    boss_name    = ui.TextInput(label='BOSS 名稱',        placeholder='例如：殘暴炎魔',          required=True,  max_length=50)
    max_members  = ui.TextInput(label='招募人數',          placeholder='例如：6',                      required=True,  max_length=3)
    leader_char  = ui.TextInput(label='隊長角色名稱',      placeholder='你在遊戲中的角色名稱',          required=True,  max_length=50)
    start_time   = ui.TextInput(label='開始時間',          placeholder='例如：今晚 21:00 / 5/10 20:30', required=True,  max_length=50)
    requirements = ui.TextInput(
        label='加入條件與備註（選填）',
        style=discord.TextStyle.paragraph,
        placeholder='例如：等級 120+，表攻 20000+',
        required=False, max_length=400,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.max_members.value)
            if count < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 招募人數必須是正整數！', ephemeral=True)
            return

        db = interaction.client.db
        gs = db.get_guild_settings(interaction.guild_id)
        raid_ch_id = gs.get('raid_channel')
        if not raid_ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定遠征隊頻道！請管理員先使用 `/設定遠征隊頻道` 設定。',
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(raid_ch_id))
        if not channel:
            await interaction.response.send_message('❌ 找不到遠征隊頻道，請重新設定。', ephemeral=True)
            return

        bar = '░' * count
        embed = discord.Embed(
            title=f'⚔️ 遠征隊招募：{self.boss_name.value}',
            color=0xE74C3C,
            timestamp=tw_now(),
        )
        embed.add_field(name='⚔️ 目標 BOSS',  value=self.boss_name.value,   inline=True)
        embed.add_field(name='👑 隊長',        value=f'{self.leader_char.value}\n{interaction.user.mention}', inline=True)
        embed.add_field(name='⏰ 開始時間',    value=self.start_time.value,  inline=True)
        embed.add_field(name='👥 目前報名',    value=f'0 / {count} 人\n`{bar}`', inline=True)
        embed.add_field(name='🎯 招募人數',    value=f'{count} 人',          inline=True)
        if self.requirements.value:
            embed.add_field(name='📋 加入條件', value=self.requirements.value, inline=False)
        embed.set_footer(text='點擊「✋ 申請加入」報名 | 僅你與隊長可查看申請詳情')

        view = RaidJoinView()
        msg  = await channel.send(embed=embed, view=view)

        active_raids[str(msg.id)] = {
            'boss':        self.boss_name.value,
            'max_members': count,
            'leader_char': self.leader_char.value,
            'leader_id':   str(interaction.user.id),
            'start_time':  self.start_time.value,
            'requirements': self.requirements.value or '',
            'channel_id':  str(channel.id),
            'guild_id':    str(interaction.guild_id),
            'applicants':  [],
            'created_at':  tw_now().isoformat(),
        }
        _save_raids()

        await interaction.response.send_message(
            f'✅ 遠征隊招募已發布至 {channel.mention}！',
            ephemeral=True,
        )


# ── 主控面板 ──────────────────────────────────────────────────────

class RaidPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='⚔️ 建立遠征隊招募', style=discord.ButtonStyle.danger,
               custom_id='raid_create_btn', row=0)
    async def create_raid(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RaidCreateModal())


# ── Cog ──────────────────────────────────────────────────────────

class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load_raids()
        bot.add_view(RaidJoinView())    # 招募文章按鈕持久化
        bot.add_view(RaidPanelView())   # 面板按鈕持久化

    # ── /遠征隊面板 ────────────────────────────────────────────
    @app_commands.command(name='遠征隊面板', description='⚔️ 在此頻道發布遠征隊招募面板（僅限管理員）')
    @admin_only()
    async def raid_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='⚔️ 遠征隊招募系統',
            description=(
                '想組遠征隊出征？點擊下方按鈕建立招募！\n\n'
                '**流程：**\n'
                '1️⃣ 點擊「建立遠征隊招募」填寫表單\n'
                '2️⃣ 機器人自動在遠征隊頻道發布公告\n'
                '3️⃣ 冒險家點「申請加入」填寫角色資料\n'
                '4️⃣ 隊長收到 DM 通知，申請人可查看自己的資料'
            ),
            color=0xE74C3C,
        )
        await interaction.response.send_message(embed=embed, view=RaidPanelView())

    # ── /設定遠征隊頻道 ─────────────────────────────────────────
    @app_commands.command(name='設定遠征隊頻道', description='設定遠征隊招募文章要發布的頻道')
    @app_commands.describe(頻道='招募文章將發布到此頻道')
    @admin_only()
    async def set_raid_channel(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['raid_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 遠征隊招募頻道已設定為 {頻道.mention}',
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
