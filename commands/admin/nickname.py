import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class Nickname(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='設定暱稱', description='設定成員的顯示名稱（留空則移除自訂名稱）')
    @app_commands.describe(成員='要設定暱稱的成員', 名稱='新的顯示名稱（留空則還原為 Discord 名稱）')
    @admin_only()
    async def slash_nickname(self, interaction: discord.Interaction,
                              成員: discord.Member, 名稱: str = ''):
        db = self.bot.db
        guild_id = interaction.guild_id

        if not 名稱:
            current = db.get_nickname(guild_id, 成員.id)
            if current:
                db.set_nickname(guild_id, 成員.id, 成員.display_name)
                await interaction.response.send_message(
                    f'✅ 已將 **{成員.display_name}** 的自訂名稱移除，還原為 `{成員.display_name}`',
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f'⚠️ **{成員.display_name}** 目前沒有設定自訂名稱。',
                    ephemeral=True
                )
        else:
            db.set_nickname(guild_id, 成員.id, 名稱)
            db.init_user(guild_id, 成員.id, 名稱)
            await interaction.response.send_message(
                f'✅ 已將 **{成員.display_name}** 的顯示名稱設定為：**{名稱}**',
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Nickname(bot))
