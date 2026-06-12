import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data'))


def _load():
    p = os.path.join(DATA_DIR, 'voice_channels.json')
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save(data):
    p = os.path.join(DATA_DIR, 'voice_channels.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get(gid: str) -> dict:
    return _load().get(gid, {})


def _set(gid: str, guild_data: dict):
    data = _load()
    data[gid] = guild_data
    _save(data)


# ── Modal：改名 ────────────────────────────────────────────────

class RenameModal(discord.ui.Modal, title='更改語音頻道名稱'):
    name_input = discord.ui.TextInput(
        label='新頻道名稱',
        placeholder='輸入新的語音頻道名稱',
        max_length=100,
    )

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel
        self.name_input.default = channel.name

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name_input.value.strip()
        if not new_name:
            await interaction.response.send_message('❌ 頻道名稱不能為空。', ephemeral=True)
            return
        try:
            await self.channel.edit(name=new_name)
            await interaction.response.send_message(
                f'✅ 頻道名稱已更改為 **{new_name}**', ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                '❌ 機器人權限不足，無法更改頻道名稱。', ephemeral=True
            )
        except discord.NotFound:
            await interaction.response.send_message(
                '❌ 找不到頻道，可能已被刪除。', ephemeral=True
            )


# ── Modal：設定人數 ────────────────────────────────────────────

class LimitModal(discord.ui.Modal, title='設定人數上限'):
    limit_input = discord.ui.TextInput(
        label='人數上限（0 = 無限制，最大 99）',
        placeholder='輸入 0~99 的數字',
        max_length=2,
    )

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel
        self.limit_input.default = str(channel.user_limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit_input.value)
            if not 0 <= val <= 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 請輸入 0~99 的整數。', ephemeral=True)
            return
        try:
            await self.channel.edit(user_limit=val)
            limit_str = '無限制' if val == 0 else f'{val} 人'
            await interaction.response.send_message(
                f'✅ 人數上限已設定為 **{limit_str}**', ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                '❌ 機器人權限不足，無法更改人數上限。', ephemeral=True
            )
        except discord.NotFound:
            await interaction.response.send_message(
                '❌ 找不到頻道，可能已被刪除。', ephemeral=True
            )


# ── 控制面板 View ──────────────────────────────────────────────

class VoiceControlView(discord.ui.View):
    def __init__(self, channel_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                '❌ 只有頻道建立者才能使用此控制面板。', ephemeral=True
            )
            return False
        return True

    def _get_channel(self, guild: discord.Guild):
        return guild.get_channel(self.channel_id)

    @discord.ui.button(label='改名', emoji='✏️', style=discord.ButtonStyle.primary)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = self._get_channel(interaction.guild)
        if not ch:
            await interaction.response.send_message('❌ 找不到頻道，可能已被刪除。', ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal(ch))

    @discord.ui.button(label='設定人數', emoji='👥', style=discord.ButtonStyle.secondary)
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = self._get_channel(interaction.guild)
        if not ch:
            await interaction.response.send_message('❌ 找不到頻道，可能已被刪除。', ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal(ch))

    @discord.ui.button(label='鎖定頻道', emoji='🔒', style=discord.ButtonStyle.danger)
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = self._get_channel(interaction.guild)
        if not ch:
            await interaction.response.send_message('❌ 找不到頻道，可能已被刪除。', ephemeral=True)
            return
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        try:
            if overwrite.connect is False:
                overwrite.connect = None
                await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message(
                    '✅ 頻道已**解鎖**，所有人可以加入。', ephemeral=True
                )
            else:
                overwrite.connect = False
                await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message(
                    '✅ 頻道已**鎖定**，其他人無法加入。', ephemeral=True
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                '❌ 機器人權限不足，無法更改頻道權限。', ephemeral=True
            )


# ── Cog ────────────────────────────────────────────────────────

class VoiceChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── 事件監聽 ──────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        gid = str(member.guild.id)
        guild_data = _get(gid)
        trigger_id = guild_data.get('trigger_channel_id')

        # 偵測加入觸發頻道
        if trigger_id and after.channel and str(after.channel.id) == trigger_id:
            await self._handle_join(member, guild_data, gid)

        # 偵測離開自動頻道且頻道已空
        if before.channel:
            active = guild_data.get('active', {})
            bid = str(before.channel.id)
            if bid in active and len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason='自動語音頻道已清空')
                except (discord.NotFound, discord.Forbidden):
                    pass
                active.pop(bid, None)
                guild_data['active'] = active
                _set(gid, guild_data)

    async def _handle_join(self, member: discord.Member, guild_data: dict, gid: str):
        guild = member.guild
        default_name = guild_data.get('default_name', '🎮 {user}的頻道')
        default_limit = guild_data.get('default_limit', 99)
        category_id = guild_data.get('category_id')

        channel_name = default_name.replace('{user}', member.display_name)
        category = guild.get_channel(int(category_id)) if category_id else None

        # 音訊相關權限 bitmask
        audio_perm = discord.Permissions(view_channel=True, connect=True, speak=True)

        # 從分類複製所有覆蓋，但強制解除所有角色/成員的音訊限制
        overwrites = {}
        if category:
            for target, cat_ow in category.overwrites.items():
                allow, deny = cat_ow.pair()
                new_deny = discord.Permissions(deny.value & ~audio_perm.value)
                new_allow = discord.Permissions(allow.value | audio_perm.value)
                overwrites[target] = discord.PermissionOverwrite.from_pair(new_allow, new_deny)

        # 確保 @everyone 明確可以看到、連線、說話
        everyone_ow = overwrites.get(guild.default_role, discord.PermissionOverwrite())
        everyone_ow.view_channel = True
        everyone_ow.connect = True
        everyone_ow.speak = True
        overwrites[guild.default_role] = everyone_ow

        # 創建者同樣明確允許（不加 manage_channels / move_members 以免機器人權限不足導致靜默失敗）
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
        )

        try:
            new_ch = await guild.create_voice_channel(
                name=channel_name,
                user_limit=default_limit,
                category=category,
                overwrites=overwrites,
                reason=f'自動語音頻道：{member.display_name}',
            )
            await member.move_to(new_ch, reason='移動到自動建立的語音頻道')
            # 觸發頻道若有靜音/耳聾設定，搬移後需手動取消，否則狀態會帶進新頻道
            try:
                await member.edit(mute=False, deafen=False, reason='取消觸發頻道的靜音狀態')
            except discord.Forbidden:
                pass
        except (discord.Forbidden, discord.HTTPException):
            return

        guild_data.setdefault('active', {})[str(new_ch.id)] = str(member.id)
        _set(gid, guild_data)

    # ── /設定語音觸發頻道 ──────────────────────────────────────
    @app_commands.command(name='設定語音觸發頻道', description='設定使用者加入後自動分配新語音頻道的觸發頻道')
    @app_commands.describe(頻道='使用者加入此語音頻道後會自動被分配新的頻道')
    @admin_only()
    async def set_trigger(self, interaction: discord.Interaction, 頻道: discord.VoiceChannel):
        gid = str(interaction.guild_id)
        guild_data = _get(gid)
        guild_data['trigger_channel_id'] = str(頻道.id)
        _set(gid, guild_data)
        await interaction.response.send_message(
            f'✅ 已將 **{頻道.name}** 設定為語音觸發頻道。\n'
            '使用者加入後，機器人將自動建立新頻道並將其移入。',
            ephemeral=True,
        )

    # ── /設定語音預設名稱 ──────────────────────────────────────
    @app_commands.command(name='設定語音預設名稱', description='設定自動建立頻道的預設名稱（{user} 會替換為使用者名稱）')
    @app_commands.describe(名稱='預設名稱，例如：🎮 {user}的頻道')
    @admin_only()
    async def set_default_name(self, interaction: discord.Interaction, 名稱: str):
        gid = str(interaction.guild_id)
        guild_data = _get(gid)
        guild_data['default_name'] = 名稱
        _set(gid, guild_data)
        preview = 名稱.replace('{user}', interaction.user.display_name)
        await interaction.response.send_message(
            f'✅ 預設名稱已設定為：`{名稱}`\n預覽：**{preview}**',
            ephemeral=True,
        )

    # ── /設定語音預設人數 ──────────────────────────────────────
    @app_commands.command(name='設定語音預設人數', description='設定自動建立頻道的預設人數上限（0 = 無限制，最大 99）')
    @app_commands.describe(人數='人數上限（0 = 無限制）')
    @admin_only()
    async def set_default_limit(self, interaction: discord.Interaction, 人數: int):
        if not 0 <= 人數 <= 99:
            await interaction.response.send_message('❌ 人數上限必須在 0~99 之間。', ephemeral=True)
            return
        gid = str(interaction.guild_id)
        guild_data = _get(gid)
        guild_data['default_limit'] = 人數
        _set(gid, guild_data)
        limit_str = '無限制' if 人數 == 0 else f'{人數} 人'
        await interaction.response.send_message(
            f'✅ 預設人數上限已設定為 **{limit_str}**', ephemeral=True
        )

    # ── /設定語音頻道分類 ──────────────────────────────────────
    @app_commands.command(name='設定語音頻道分類', description='設定自動建立的語音頻道所屬分類（不填則不指定分類）')
    @app_commands.describe(分類='語音頻道要建立在哪個分類下（可選）')
    @admin_only()
    async def set_category(
        self, interaction: discord.Interaction, 分類: discord.CategoryChannel = None
    ):
        gid = str(interaction.guild_id)
        guild_data = _get(gid)
        if 分類:
            guild_data['category_id'] = str(分類.id)
            msg = f'✅ 自動語音頻道將建立在分類 **{分類.name}** 下。'
        else:
            guild_data.pop('category_id', None)
            msg = '✅ 已清除分類設定，語音頻道將建立在伺服器預設位置。'
        _set(gid, guild_data)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /語音頻道設定 ──────────────────────────────────────────
    @app_commands.command(name='語音頻道設定', description='查看目前的自動語音頻道設定')
    @admin_only()
    async def view_settings(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        guild_data = _get(gid)

        trigger_id = guild_data.get('trigger_channel_id')
        trigger_ch = interaction.guild.get_channel(int(trigger_id)) if trigger_id else None
        category_id = guild_data.get('category_id')
        category_ch = interaction.guild.get_channel(int(category_id)) if category_id else None
        active = guild_data.get('active', {})
        limit = guild_data.get('default_limit', 99)

        embed = discord.Embed(title='🎛️ 自動語音頻道設定', color=0x5865F2)
        embed.add_field(
            name='觸發頻道',
            value=trigger_ch.mention if trigger_ch else '❌ 尚未設定',
            inline=True,
        )
        embed.add_field(
            name='預設名稱',
            value=f"`{guild_data.get('default_name', '🎮 {user}的頻道')}`",
            inline=True,
        )
        embed.add_field(
            name='預設人數',
            value='無限制' if limit == 0 else f'{limit} 人',
            inline=True,
        )
        embed.add_field(
            name='頻道分類',
            value=category_ch.name if category_ch else '（無分類）',
            inline=True,
        )
        embed.add_field(
            name='目前活躍頻道',
            value=f'{len(active)} 個' if active else '無',
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /我的語音頻道 ─────────────────────────────────────────
    @app_commands.command(name='我的語音頻道', description='取得你目前語音頻道的控制面板')
    async def my_channel(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        guild_data = _get(gid)
        active = guild_data.get('active', {})
        uid = str(interaction.user.id)

        owned = [cid for cid, oid in active.items() if oid == uid]
        if not owned:
            await interaction.response.send_message(
                '❌ 你目前沒有正在使用的自動語音頻道。', ephemeral=True
            )
            return

        ch_id = int(owned[0])
        ch = interaction.guild.get_channel(ch_id)
        if not ch:
            active.pop(str(ch_id), None)
            guild_data['active'] = active
            _set(gid, guild_data)
            await interaction.response.send_message(
                '❌ 找不到你的語音頻道，可能已被刪除。', ephemeral=True
            )
            return

        limit_str = '無限制' if ch.user_limit == 0 else f'{ch.user_limit} 人'
        embed = discord.Embed(
            title='🎛️ 語音頻道控制面板',
            description=f'正在管理：**{ch.name}**\n使用下方按鈕來調整你的頻道。',
            color=0x5865F2,
        )
        embed.add_field(
            name='📌 目前設定',
            value=f'名稱：**{ch.name}**\n人數上限：**{limit_str}**',
            inline=False,
        )
        view = VoiceControlView(ch_id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(VoiceChannelCog(bot))
