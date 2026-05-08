import discord
from discord import app_commands
from discord.ext import commands


def server_admin_only():
    """只有 Discord 伺服器管理員（非機器人管理員）可用。"""
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.guild and interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


class AdminManage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='新增機器人管理員', description='授予指定成員機器人管理員權限（需伺服器管理員）')
    @app_commands.describe(成員='要授予機器人管理員的成員')
    @server_admin_only()
    async def slash_add_admin(self, interaction: discord.Interaction, 成員: discord.Member):
        db = self.bot.db
        guild_id = interaction.guild_id
        db.add_bot_admin(guild_id, 成員.id)
        name = db.get_display_name(guild_id, 成員.id, fallback=成員.display_name)
        await interaction.response.send_message(
            f'✅ 已將 **{name}** 設定為機器人管理員。', ephemeral=True
        )

    @app_commands.command(name='移除機器人管理員', description='撤銷指定成員的機器人管理員權限（需伺服器管理員）')
    @app_commands.describe(成員='要撤銷機器人管理員的成員')
    @server_admin_only()
    async def slash_remove_admin(self, interaction: discord.Interaction, 成員: discord.Member):
        db = self.bot.db
        guild_id = interaction.guild_id
        success = db.remove_bot_admin(guild_id, 成員.id)
        name = db.get_display_name(guild_id, 成員.id, fallback=成員.display_name)
        if success:
            await interaction.response.send_message(
                f'✅ 已將 **{name}** 從機器人管理員中移除。', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f'⚠️ **{name}** 不是機器人管理員。', ephemeral=True
            )

    @app_commands.command(name='管理員清單', description='查看機器人管理員清單')
    @server_admin_only()
    async def slash_list_admins(self, interaction: discord.Interaction):
        db = self.bot.db
        guild_id = interaction.guild_id
        gs = db.get_guild_settings(guild_id)
        admins = gs.get('bot_admins', [])

        embed = discord.Embed(title='🔧 機器人管理員清單', color=0xFEE75C)
        if not admins:
            embed.description = '目前沒有設定任何機器人管理員。\n只有 Discord 伺服器管理員可使用管理指令。'
        else:
            lines = []
            for uid in admins:
                name = db.get_display_name(guild_id, uid, fallback=f'ID: {uid}')
                m = interaction.guild.get_member(int(uid))
                mention = m.mention if m else f'`{uid}`'
                lines.append(f'• {name} ({mention})')
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'共 {len(admins)} 位機器人管理員')

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminManage(bot))
