import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only

CHECKIN_PANEL_DESC = (
    '歡迎使用簽到系統！點擊下方按鈕進行操作：\n\n'
    '✅ **簽到** — 每日簽到（獲得 1 枚簽到幣）\n'
    '📊 **簽到排行** — 查看總簽到次數排行\n'
    '🔥 **連續簽到排行** — 查看連續簽到天數排行\n'
    '💰 **查詢簽到幣** — 查看目前擁有的簽到幣\n'
    '🎫 **查詢抽獎卷** — 查看周抽及月抽獎卷數量\n'
    '🔄 **兌換抽獎卷** — 用簽到幣兌換抽獎卷\n\n'
    '> 所有回應只有你自己看得到'
)


class InitSetupView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id          = author_id
        self.panel_channel      = None   # 簽到面板
        self.news_channel       = None   # 楓星新聞
        self.raid_channel       = None   # 遠征隊招募
        self.announcement_channel = None # 公告系統

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                '❌ 只有發出指令的管理員才能操作。', ephemeral=True)
            return False
        return True

    # ── Row 0：簽到面板頻道（必填）───────────────────────────────
    @discord.ui.select(
        cls           = discord.ui.ChannelSelect,
        channel_types = [discord.ChannelType.text],
        placeholder   = '📋 第一步：選擇簽到面板放置的頻道（必填）',
        row           = 0,
    )
    async def select_panel(self, interaction: discord.Interaction,
                           select: discord.ui.ChannelSelect):
        self.panel_channel = select.values[0]
        await interaction.response.defer()

    # ── Row 1：楓星新聞頻道（選填）──────────────────────────────
    @discord.ui.select(
        cls           = discord.ui.ChannelSelect,
        channel_types = [discord.ChannelType.text],
        placeholder   = '🗞️ 第二步：楓星官網新聞自動發布的頻道（選填）',
        row           = 1,
    )
    async def select_news(self, interaction: discord.Interaction,
                          select: discord.ui.ChannelSelect):
        self.news_channel = select.values[0]
        await interaction.response.defer()

    # ── Row 2：遠征隊招募頻道（選填）────────────────────────────
    @discord.ui.select(
        cls           = discord.ui.ChannelSelect,
        channel_types = [discord.ChannelType.text],
        placeholder   = '⚔️ 第三步：遠征隊招募公告要發布的頻道（選填）',
        row           = 2,
    )
    async def select_raid(self, interaction: discord.Interaction,
                          select: discord.ui.ChannelSelect):
        self.raid_channel = select.values[0]
        await interaction.response.defer()

    # ── Row 3：公告系統頻道（選填）──────────────────────────────
    @discord.ui.select(
        cls           = discord.ui.ChannelSelect,
        channel_types = [discord.ChannelType.text],
        placeholder   = '📢 第四步：管理員公告要發布的頻道（選填）',
        row           = 3,
    )
    async def select_announcement(self, interaction: discord.Interaction,
                                  select: discord.ui.ChannelSelect):
        self.announcement_channel = select.values[0]
        await interaction.response.defer()

    # ── Row 4：確認 / 取消 ───────────────────────────────────────
    @discord.ui.button(label='確認設定', style=discord.ButtonStyle.success,
                       emoji='✅', row=4)
    async def confirm(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        if not self.panel_channel:
            await interaction.response.send_message(
                '❌ 請先選擇簽到面板要放置的頻道！', ephemeral=True)
            return

        db       = interaction.client.db
        guild_id = interaction.guild_id
        gs       = db.get_guild_settings(guild_id)

        # ─ 儲存各頻道設定 ─
        if self.news_channel:
            gs['news_channel'] = str(self.news_channel.id)
        if self.raid_channel:
            gs['raid_channel'] = str(self.raid_channel.id)
        if self.announcement_channel:
            gs['announcement_channel'] = str(self.announcement_channel.id)
        db.save_guild_settings(guild_id, gs)

        # ─ 簽到頻道設定 ─
        db.add_checkin_channel(guild_id, self.panel_channel.id)
        ch_settings = db.get_channel_settings(guild_id, self.panel_channel.id)
        db.save_channel_settings(guild_id, self.panel_channel.id, ch_settings)

        # ─ 發送簽到面板 ─
        from commands.user.panel import CheckInView
        checkin_embed = discord.Embed(
            title       = '📋 簽到控制台',
            description = CHECKIN_PANEL_DESC,
            color       = 0x5865F2,
        )
        try:
            await self.panel_channel.send(embed=checkin_embed, view=CheckInView())
        except discord.Forbidden:
            await interaction.response.send_message(
                f'❌ Bot 沒有在 {self.panel_channel.mention} 發送訊息的權限，請確認後重試。',
                ephemeral=True)
            return

        # ─ 停用所有元件 ─
        for item in self.children:
            item.disabled = True

        # ─ 完成訊息 ─
        lines = [
            '✅  **初始化設定完成！**\n',
            f'📋  簽到面板已發布至 {self.panel_channel.mention}',
        ]
        if self.news_channel:
            lines.append(f'🗞️  楓星新聞將自動發布至 {self.news_channel.mention}')
        else:
            lines.append('🗞️  楓星新聞頻道未設定（可用 `/設定公告頻道` 補設）')

        if self.raid_channel:
            lines.append(f'⚔️  遠征隊招募將發布至 {self.raid_channel.mention}')
        else:
            lines.append('⚔️  遠征隊頻道未設定（可用 `/設定遠征隊頻道` 補設）')

        if self.announcement_channel:
            lines.append(f'📢  公告將發布至 {self.announcement_channel.mention}')
        else:
            lines.append('📢  公告頻道未設定（可用 `/設定公告發布頻道` 補設）')

        lines += [
            '',
            '**接下來請在管理員頻道執行以下指令發布各功能面板：**',
            '　`/遠征隊面板` — 發布遠征隊招募面板',
            '　`/組隊面板` — 發布組隊任務面板',
            '　`/捐獻面板` — 發布捐獻系統面板',
            '　`/公告面板` — 發布公告管理面板',
            '',
            '若要補設其他頻道：',
            '　`/設定捐獻頻道` — 捐獻通知頻道',
            '　`/設定組隊頻道` — 組隊任務頻道',
        ]

        await interaction.response.edit_message(
            content='\n'.join(lines), embed=None, view=self)
        self.stop()

    @discord.ui.button(label='取消', style=discord.ButtonStyle.secondary,
                       emoji='✖️', row=4)
    async def cancel(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content='❌ 已取消初始化設定。', embed=None, view=self)
        self.stop()


class InitSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name        = '初始化設定',
        description = '設定各功能頻道，初次使用請先執行',
    )
    @admin_only()
    async def slash_init(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '⚙️  初始化設定',
            description = (
                '請依序選擇各功能頻道，完成後點擊「確認設定」。\n\n'
                '**📋 簽到面板頻道**（必填）\n'
                '　Bot 會在此頻道發送簽到面板，成員點擊按鈕即可簽到\n\n'
                '**🗞️ 楓星新聞頻道**（選填）\n'
                '　楓星官網最新公告會自動擷取並發布至此\n\n'
                '**⚔️ 遠征隊招募頻道**（選填）\n'
                '　成員建立遠征隊後招募公告會出現在此\n\n'
                '**📢 公告系統頻道**（選填）\n'
                '　管理員透過公告面板發布的公告會出現在此\n\n'
                '> ⏱️ 此表單 **180 秒**後自動失效\n'
                '> 捐獻通知頻道請事後使用 `/設定捐獻頻道` 設定'
            ),
            color = 0x5865F2,
        )
        view = InitSetupView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(InitSetup(bot))
