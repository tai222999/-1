import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only

PANEL_EMBED_DESC = (
    '歡迎使用簽到系統！點擊下方按鈕進行操作：\n\n'
    '✅ **簽到** — 每日簽到\n'
    '📊 **簽到排行** — 查看總簽到次數排行\n'
    '🔥 **連續簽到排行** — 查看連續簽到天數排行\n\n'
    '> 所有回應只有你自己看得到'
)


class InitSetupView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id        = author_id
        self.panel_channel    = None
        self.announce_channel = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ 只有發出指令的管理員才能操作。', ephemeral=True)
            return False
        return True

    # ── 選擇簽到面板頻道 ─────────────────────────────────────────
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder='📋 第一步：選擇簽到面板放置的頻道',
        row=0
    )
    async def select_panel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.panel_channel = select.values[0]
        await interaction.response.defer()

    # ── 選擇公告頻道 ─────────────────────────────────────────────
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder='📢 第二步：選擇楓星公告自動發布的頻道',
        row=1
    )
    async def select_announce(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.announce_channel = select.values[0]
        await interaction.response.defer()

    # ── 確認 ─────────────────────────────────────────────────────
    @discord.ui.button(label='確認設定', style=discord.ButtonStyle.success, emoji='✅', row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.panel_channel:
            await interaction.response.send_message('❌ 請先選擇簽到面板要放置的頻道！', ephemeral=True)
            return

        db       = interaction.client.db
        guild_id = interaction.guild_id

        # 儲存公告頻道
        if self.announce_channel:
            gs = db.get_guild_settings(guild_id)
            gs['news_channel'] = str(self.announce_channel.id)
            db.save_guild_settings(guild_id, gs)

        # 將面板頻道設為簽到頻道
        db.add_checkin_channel(guild_id, self.panel_channel.id)
        # 確保頻道設定存在（讓排程器能偵測到）
        ch_settings = db.get_channel_settings(guild_id, self.panel_channel.id)
        db.save_channel_settings(guild_id, self.panel_channel.id, ch_settings)

        # 發送簽到面板
        from commands.user.panel import CheckInView
        panel_embed = discord.Embed(
            title='📋 簽到控制台',
            description=PANEL_EMBED_DESC,
            color=0x5865F2
        )
        try:
            await self.panel_channel.send(embed=panel_embed, view=CheckInView())
        except discord.Forbidden:
            await interaction.response.send_message(
                f'❌ Bot 沒有在 {self.panel_channel.mention} 發送訊息的權限，請確認頻道權限後重試。',
                ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True

        lines = [
            '✅ **初始化設定完成！**',
            f'📋 簽到面板已發布至 {self.panel_channel.mention}',
        ]
        if self.announce_channel:
            lines.append(f'📢 楓星公告將自動發布至 {self.announce_channel.mention}')
        else:
            lines.append('📢 公告頻道未設定（之後可用 `/設定公告頻道` 設定）')

        await interaction.response.edit_message(
            content='\n'.join(lines), embed=None, view=self
        )
        self.stop()

    # ── 取消 ─────────────────────────────────────────────────────
    @discord.ui.button(label='取消', style=discord.ButtonStyle.secondary, emoji='✖️', row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content='❌ 已取消初始化設定。', embed=None, view=self)
        self.stop()


class InitSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='初始化設定', description='設定簽到面板與公告頻道（初次使用請先執行）')
    @admin_only()
    async def slash_init(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='⚙️ 初始化設定',
            description=(
                '請依序完成以下選擇，然後點擊「確認設定」：\n\n'
                '**📋 簽到面板頻道**\n'
                '　Bot 會在此頻道自動發送含按鈕的簽到面板\n\n'
                '**📢 楓星公告頻道**\n'
                '　楓星官網的最新公告會自動擷取並發布到此頻道\n\n'
                '⏱️ 此表單 **120 秒**後自動失效'
            ),
            color=0x5865F2
        )
        view = InitSetupView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(InitSetup(bot))
