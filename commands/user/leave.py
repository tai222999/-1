import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timezone, timedelta

from utils.database import _load, _save
from utils.helpers import admin_only

LEAVE_FILE = 'leave.json'
_TW_TZ = timezone(timedelta(hours=8))

PANEL_DESC = (
    '如需請假，請點擊「📝 申請請假」填寫請假單。\n\n'
    '請假結束後，**請記得回來點擊「🗑️ 刪除請假紀錄」**，讓其他成員知道你已歸隊！\n\n'
    '> 所有操作只有你自己看得到'
)


def _load_leaves() -> dict:
    data = _load(LEAVE_FILE)
    return data if isinstance(data, dict) else {}


def _save_leaves(data: dict):
    _save(LEAVE_FILE, data)


def _leave_embed(record: dict, user: discord.Member) -> discord.Embed:
    embed = discord.Embed(title='🏖️ 請假通知', color=0xE67E22)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.add_field(name='目前所在公會',  value=record['session'],    inline=True)
    embed.add_field(name='遊戲暱稱',     value=record['nickname'],   inline=True)
    embed.add_field(name='MapleWordsID', value=record['maple_id'],   inline=True)
    embed.add_field(name='請假日期',     value=record['leave_date'], inline=True)
    embed.add_field(name='請假原因',     value=record['reason'],     inline=False)
    embed.set_footer(text=f'申請時間：{record["submitted_at"]}')
    return embed


# ── 請假表單 ──────────────────────────────────────────────────────

class LeaveModal(ui.Modal, title='📝 請假申請'):
    session = ui.TextInput(
        label='目前所在公會',
        placeholder='一會/二會',
        required=True, max_length=30,
    )
    nickname = ui.TextInput(
        label='遊戲暱稱',
        placeholder='你的遊戲內名稱',
        required=True, max_length=50,
    )
    maple_id = ui.TextInput(
        label='MapleWordsID',
        placeholder='MapleWords 必填！！！',
        required=True, max_length=50,
    )
    leave_date = ui.TextInput(
        label='請假日期',
        placeholder='例如：2026-05-15 或 5/15～5/17',
        required=True, max_length=50,
    )
    reason = ui.TextInput(
        label='請假原因',
        style=discord.TextStyle.paragraph,
        placeholder='請簡述請假原因',
        required=True, max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        data       = _load_leaves()
        guild_data = data.setdefault(guild_id, {})

        if user_id in guild_data:
            await interaction.response.send_message(
                '⚠️ 你目前已有一筆請假紀錄！\n'
                '請先點擊「🗑️ 刪除請假紀錄」清除後，再重新申請。',
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        now_tw = datetime.now(_TW_TZ).strftime('%Y-%m-%d %H:%M')
        record = {
            'session':      self.session.value.strip(),
            'nickname':     self.nickname.value.strip(),
            'maple_id':     self.maple_id.value.strip(),
            'leave_date':   self.leave_date.value.strip(),
            'reason':       self.reason.value.strip(),
            'submitted_at': now_tw,
            'channel_id':   interaction.channel_id,
            'message_id':   None,
        }
        guild_data[user_id] = record
        _save_leaves(data)

        # 公開發布請假公告
        msg = await interaction.channel.send(embed=_leave_embed(record, interaction.user))

        # 補存 message_id
        guild_data[user_id]['message_id'] = msg.id
        _save_leaves(data)

        await interaction.followup.send(
            '✅ 請假申請已送出！\n\n'
            '⚠️ **請假結束後，記得回來點擊「🗑️ 刪除請假紀錄」，讓大家知道你已歸隊！**',
            ephemeral=True,
        )


# ── 請假面板（持久化）────────────────────────────────────────────

class LeavePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='申請請假', style=discord.ButtonStyle.primary,
        emoji='📝', custom_id='leave_apply_btn', row=0,
    )
    async def btn_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LeaveModal())

    @discord.ui.button(
        label='刪除請假紀錄', style=discord.ButtonStyle.danger,
        emoji='🗑️', custom_id='leave_delete_btn', row=0,
    )
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        data       = _load_leaves()
        guild_data = data.get(guild_id, {})

        if user_id not in guild_data:
            await interaction.response.send_message(
                '❌ 你目前沒有任何請假紀錄。',
                ephemeral=True,
            )
            return

        record = guild_data.pop(user_id)
        _save_leaves(data)

        # 嘗試刪除公開的請假公告訊息
        msg_id = record.get('message_id')
        ch_id  = record.get('channel_id')
        if msg_id and ch_id:
            ch = interaction.guild.get_channel(int(ch_id))
            if ch:
                try:
                    msg = await ch.fetch_message(int(msg_id))
                    await msg.delete()
                except Exception:
                    pass

        await interaction.response.send_message(
            '✅ 已刪除請假紀錄，歡迎回來！',
            ephemeral=True,
        )


# ── Cog ──────────────────────────────────────────────────────────

class LeaveCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(LeavePanelView())

    @app_commands.command(name='請假面板', description='發布請假申請面板（僅限管理員）')
    @admin_only()
    async def slash_leave_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='🏖️ 請假系統',
            description=PANEL_DESC,
            color=0xE67E22,
        )
        await interaction.response.send_message(embed=embed, view=LeavePanelView())


async def setup(bot):
    await bot.add_cog(LeaveCog(bot))
