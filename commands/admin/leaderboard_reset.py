import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class ConfirmResetView(discord.ui.View):
    """按鈕確認，限原管理員操作，timeout 30 秒。"""

    def __init__(self, author_id: int, guild_id: int, board_type: str, board_name: str):
        super().__init__(timeout=30)
        self.author_id  = author_id
        self.guild_id   = guild_id
        self.board_type = board_type
        self.board_name = board_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ 只有發出指令的管理員才能操作。', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='確認重置', style=discord.ButtonStyle.danger, emoji='⚠️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        interaction.client.db.reset_leaderboard(self.guild_id, self.board_type)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f'✅ **{self.board_name}** 已成功重置！所有相關數據已清零。',
            embed=None, view=self
        )
        self.stop()

    @discord.ui.button(label='取消', style=discord.ButtonStyle.secondary, emoji='✖️')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content='❌ 已取消重置操作。', embed=None, view=self
        )
        self.stop()


class LeaderboardReset(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='重置排行榜', description='重置簽到或未簽到排行榜（操作無法復原）')
    @app_commands.describe(類型='要重置的排行榜')
    @app_commands.choices(類型=[
        app_commands.Choice(name='簽到排行榜（清空所有人簽到紀錄）', value='wl'),
        app_commands.Choice(name='未簽到排行榜（清空所有人未簽到紀錄）', value='ll'),
    ])
    @admin_only()
    async def slash_reset_leaderboard(self, interaction: discord.Interaction,
                                       類型: app_commands.Choice[str]):
        board_name = '簽到排行榜' if 類型.value == 'wl' else '未簽到排行榜'

        embed = discord.Embed(
            title=f'⚠️ 確認重置{board_name}',
            description=(
                f'你即將重置 **{board_name}**，此操作**無法復原**！\n\n'
                f'請點擊下方按鈕確認或取消（30 秒內有效）。'
            ),
            color=0xED4245
        )
        view = ConfirmResetView(interaction.user.id, interaction.guild_id, 類型.value, board_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LeaderboardReset(bot))
