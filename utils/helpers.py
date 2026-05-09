from discord import app_commands
import discord
from discord import ui

LB_PAGE_SIZE = 20


def admin_only():
    """Slash command check: 只允許伺服器管理員或機器人管理員使用。"""
    async def predicate(interaction) -> bool:
        if not interaction.guild:
            return False
        return interaction.client.db.is_admin(interaction.guild_id, interaction.user)
    return app_commands.check(predicate)


class LeaderboardView(ui.View):
    """通用分頁排行榜 View（entries 為 [(name, value), ...] 清單）。"""

    def __init__(self, entries: list, title: str, color: int,
                 author_id: int, page: int = 0):
        super().__init__(timeout=120)
        self.entries     = entries
        self.title       = title
        self.color       = color
        self.author_id   = author_id
        self.page        = page
        self.total_pages = max(1, (len(entries) + LB_PAGE_SIZE - 1) // LB_PAGE_SIZE)
        self._refresh()

    def _refresh(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        start        = self.page * LB_PAGE_SIZE
        page_entries = self.entries[start:start + LB_PAGE_SIZE]
        medals       = {1: '🥇', 2: '🥈', 3: '🥉'}

        embed = discord.Embed(title=self.title, color=self.color)
        if not page_entries:
            embed.description = '目前沒有任何資料。'
        else:
            lines = []
            for i, (name, value) in enumerate(page_entries):
                rank   = start + i + 1
                prefix = medals.get(rank, f'`{rank:>3}.`')
                lines.append(f'{prefix} **{name}** — {value}')
            embed.description = '\n'.join(lines)

        if self.total_pages > 1:
            embed.set_footer(
                text=f'第 {self.page + 1} / {self.total_pages} 頁 ｜ 共 {len(self.entries)} 筆'
            )
        else:
            embed.set_footer(text=f'共 {len(self.entries)} 筆')
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                '❌ 只有發出指令的成員才能翻頁。', ephemeral=True)
            return False
        return True

    @ui.button(label='◀ 上一頁', style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page -= 1
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label='下一頁 ▶', style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page += 1
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
