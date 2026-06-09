import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data'))

STYLE_MAP = {
    'primary':   discord.ButtonStyle.primary,
    'secondary': discord.ButtonStyle.secondary,
    'success':   discord.ButtonStyle.success,
    'danger':    discord.ButtonStyle.danger,
}


def _load():
    p = os.path.join(DATA_DIR, 'role_panels.json')
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save(data):
    p = os.path.join(DATA_DIR, 'role_panels.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_id(guild_panels: dict) -> str:
    existing = [int(k) for k in guild_panels if k.isdigit()]
    return str(max(existing) + 1) if existing else '1'


def _build_embed(panel: dict) -> discord.Embed:
    return discord.Embed(
        title=panel.get('title', '身分組選擇'),
        description=panel.get('description', '點擊下方按鈕來領取或移除身分組。'),
        color=panel.get('color', 0x5865F2),
    )


class RolePanelButton(discord.ui.Button):
    def __init__(self, label: str, role_id: str, emoji=None,
                 style: discord.ButtonStyle = discord.ButtonStyle.primary):
        super().__init__(
            label=label,
            emoji=emoji or None,
            style=style,
            custom_id=f'rp:{role_id}',
        )
        self._role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(int(self._role_id))
        if not role:
            await interaction.response.send_message('❌ 找不到此身分組，可能已被刪除。', ephemeral=True)
            return
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f'✅ 已移除身分組：**{role.name}**', ephemeral=True)
            else:
                await member.add_roles(role)
                await interaction.response.send_message(f'✅ 已獲得身分組：**{role.name}**', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message('❌ 機器人權限不足，無法操作此身分組。', ephemeral=True)


class RolePanelView(discord.ui.View):
    def __init__(self, buttons_data: list):
        super().__init__(timeout=None)
        for btn in buttons_data:
            self.add_item(RolePanelButton(
                label=btn['label'],
                role_id=btn['role_id'],
                emoji=btn.get('emoji') or None,
                style=STYLE_MAP.get(btn.get('style', 'primary'), discord.ButtonStyle.primary),
            ))


class RolePanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """重啟後重新註冊所有面板的持久化 View。"""
        data = _load()
        for guild_panels in data.values():
            for panel in guild_panels.values():
                if panel.get('message_id') and panel.get('buttons'):
                    view = RolePanelView(panel['buttons'])
                    self.bot.add_view(view, message_id=int(panel['message_id']))

    # ── /建立身分組面板 ──────────────────────────────────────────
    @app_commands.command(name='建立身分組面板', description='建立一個可自訂按鈕的身分組選擇面板')
    @app_commands.describe(
        標題='面板標題文字',
        描述='面板說明內文',
        顏色='嵌入框顏色（十六進位，例如 5865F2）',
    )
    @admin_only()
    async def create_panel(self, interaction: discord.Interaction,
                           標題: str,
                           描述: str = '點擊下方按鈕來領取或移除身分組。',
                           顏色: str = '5865F2'):
        try:
            color = int(顏色.lstrip('#'), 16)
        except ValueError:
            color = 0x5865F2

        data = _load()
        gid = str(interaction.guild_id)
        data.setdefault(gid, {})
        panel_id = _next_id(data[gid])
        data[gid][panel_id] = {
            'title': 標題,
            'description': 描述,
            'color': color,
            'message_id': None,
            'channel_id': None,
            'buttons': [],
        }
        _save(data)

        embed = discord.Embed(title='✅ 面板已建立', color=0x57F287)
        embed.add_field(name='面板 ID', value=f'`{panel_id}`', inline=True)
        embed.add_field(name='標題', value=標題, inline=True)
        embed.add_field(name='描述', value=描述, inline=False)
        embed.set_footer(text=f'使用 /新增身分組按鈕 面板id:{panel_id} 來新增按鈕')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /新增身分組按鈕 ──────────────────────────────────────────
    @app_commands.command(name='新增身分組按鈕', description='新增一個按鈕到身分組面板')
    @app_commands.describe(
        面板id='目標面板 ID（用 /身分組面板清單 查看）',
        身分組='點擊按鈕後要獲得或移除的身分組',
        按鈕文字='按鈕上顯示的文字',
        表情符號='按鈕左側的表情符號（可選，例如 ⚔️）',
        按鈕樣式='按鈕顏色',
    )
    @app_commands.choices(按鈕樣式=[
        app_commands.Choice(name='藍色 (primary)',   value='primary'),
        app_commands.Choice(name='灰色 (secondary)', value='secondary'),
        app_commands.Choice(name='綠色 (success)',   value='success'),
        app_commands.Choice(name='紅色 (danger)',    value='danger'),
    ])
    @admin_only()
    async def add_button(self, interaction: discord.Interaction,
                         面板id: str, 身分組: discord.Role, 按鈕文字: str,
                         表情符號: str = None, 按鈕樣式: str = 'primary'):
        data = _load()
        gid = str(interaction.guild_id)

        if gid not in data or 面板id not in data[gid]:
            await interaction.response.send_message(
                f'❌ 找不到面板 `{面板id}`，請先使用 `/建立身分組面板`。', ephemeral=True)
            return

        buttons = data[gid][面板id].setdefault('buttons', [])

        if len(buttons) >= 25:
            await interaction.response.send_message('❌ 一個面板最多只能有 25 個按鈕。', ephemeral=True)
            return

        if any(b['role_id'] == str(身分組.id) for b in buttons):
            await interaction.response.send_message(
                f'❌ 身分組 **{身分組.name}** 已在此面板中。', ephemeral=True)
            return

        buttons.append({
            'label':   按鈕文字,
            'emoji':   表情符號,
            'role_id': str(身分組.id),
            'style':   按鈕樣式,
        })
        _save(data)

        await interaction.response.send_message(
            f'✅ 已新增按鈕 **{按鈕文字}** → **{身分組.name}** 到面板 `{面板id}`\n'
            f'目前共 **{len(buttons)}** 個按鈕。\n'
            f'使用 `/發送身分組面板 面板id:{面板id}` 來發送或更新面板。',
            ephemeral=True)

    # ── /移除身分組按鈕 ──────────────────────────────────────────
    @app_commands.command(name='移除身分組按鈕', description='從面板中移除指定身分組的按鈕')
    @app_commands.describe(
        面板id='目標面板 ID',
        身分組='要移除的身分組',
    )
    @admin_only()
    async def remove_button(self, interaction: discord.Interaction,
                            面板id: str, 身分組: discord.Role):
        data = _load()
        gid = str(interaction.guild_id)

        if gid not in data or 面板id not in data[gid]:
            await interaction.response.send_message(f'❌ 找不到面板 `{面板id}`。', ephemeral=True)
            return

        panel = data[gid][面板id]
        before = len(panel.get('buttons', []))
        panel['buttons'] = [b for b in panel.get('buttons', []) if b['role_id'] != str(身分組.id)]

        if len(panel['buttons']) == before:
            await interaction.response.send_message(
                f'❌ 面板 `{面板id}` 中找不到身分組 **{身分組.name}** 的按鈕。', ephemeral=True)
            return

        _save(data)
        await interaction.response.send_message(
            f'✅ 已從面板 `{面板id}` 移除 **{身分組.name}** 的按鈕。\n'
            f'使用 `/發送身分組面板 面板id:{面板id}` 更新面板訊息。',
            ephemeral=True)

    # ── /發送身分組面板 ──────────────────────────────────────────
    @app_commands.command(name='發送身分組面板', description='將面板發送到頻道（已發送的話則更新原訊息）')
    @app_commands.describe(
        面板id='要發送的面板 ID',
        頻道='目標頻道（預設為目前頻道）',
    )
    @admin_only()
    async def send_panel(self, interaction: discord.Interaction,
                         面板id: str, 頻道: discord.TextChannel = None):
        data = _load()
        gid = str(interaction.guild_id)

        if gid not in data or 面板id not in data[gid]:
            await interaction.response.send_message(f'❌ 找不到面板 `{面板id}`。', ephemeral=True)
            return

        panel = data[gid][面板id]
        buttons = panel.get('buttons', [])

        if not buttons:
            await interaction.response.send_message(
                '❌ 此面板沒有任何按鈕，請先用 `/新增身分組按鈕` 新增按鈕。', ephemeral=True)
            return

        embed = _build_embed(panel)
        view = RolePanelView(buttons)
        existing_msg_id = panel.get('message_id')
        existing_ch_id  = panel.get('channel_id')

        # 嘗試更新現有訊息
        if existing_msg_id and existing_ch_id:
            try:
                ch = interaction.guild.get_channel(int(existing_ch_id))
                if ch:
                    msg = await ch.fetch_message(int(existing_msg_id))
                    await msg.edit(embed=embed, view=view)
                    self.bot.add_view(view, message_id=int(existing_msg_id))
                    await interaction.response.send_message(
                        f'✅ 已更新 {ch.mention} 中的面板訊息。', ephemeral=True)
                    return
            except (discord.NotFound, discord.HTTPException):
                pass  # 原訊息不存在，改為發送新訊息

        target = 頻道 or interaction.channel
        await interaction.response.defer(ephemeral=True)
        msg = await target.send(embed=embed, view=view)
        self.bot.add_view(view, message_id=msg.id)

        panel['message_id'] = str(msg.id)
        panel['channel_id'] = str(target.id)
        _save(data)

        await interaction.followup.send(f'✅ 已在 {target.mention} 發送面板。', ephemeral=True)

    # ── /刪除身分組面板 ──────────────────────────────────────────
    @app_commands.command(name='刪除身分組面板', description='刪除一個身分組面板設定（不刪除頻道訊息）')
    @app_commands.describe(面板id='要刪除的面板 ID')
    @admin_only()
    async def delete_panel(self, interaction: discord.Interaction, 面板id: str):
        data = _load()
        gid = str(interaction.guild_id)

        if gid not in data or 面板id not in data[gid]:
            await interaction.response.send_message(f'❌ 找不到面板 `{面板id}`。', ephemeral=True)
            return

        panel = data[gid].pop(面板id)
        _save(data)

        await interaction.response.send_message(
            f'✅ 已刪除面板 `{面板id}`（{panel.get("title", "無標題")}）。\n'
            f'⚠️ 頻道中的面板訊息不會被自動刪除，但按鈕將停止運作。',
            ephemeral=True)

    # ── /身分組面板清單 ──────────────────────────────────────────
    @app_commands.command(name='身分組面板清單', description='查看此伺服器的所有身分組面板')
    @admin_only()
    async def list_panels(self, interaction: discord.Interaction):
        data = _load()
        panels = data.get(str(interaction.guild_id), {})

        if not panels:
            await interaction.response.send_message(
                '📋 此伺服器目前沒有任何身分組面板。', ephemeral=True)
            return

        embed = discord.Embed(title='📋 身分組面板清單', color=0x5865F2)
        for panel_id, panel in panels.items():
            ch_id = panel.get('channel_id')
            ch_obj = interaction.guild.get_channel(int(ch_id)) if ch_id else None
            location = ch_obj.mention if ch_obj else '尚未發送'

            lines = []
            for btn in panel.get('buttons', []):
                role = interaction.guild.get_role(int(btn['role_id']))
                rname = role.name if role else '（已刪除）'
                emoji = btn.get('emoji') or ''
                lines.append(f"　`{emoji} {btn['label']}` → **{rname}**")

            embed.add_field(
                name=f"ID `{panel_id}` — {panel.get('title', '（無標題）')}",
                value=(
                    f"📍 位置：{location}\n"
                    f"🔘 按鈕（{len(lines)} 個）：\n"
                    + ('\n'.join(lines) if lines else '　（無按鈕）')
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RolePanel(bot))
