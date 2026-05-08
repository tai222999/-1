import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class Blacklist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='加入黑名單', description='禁止指定成員在此頻道簽到')
    @app_commands.describe(成員='要加入黑名單的成員')
    @admin_only()
    async def slash_blacklist_add(self, interaction: discord.Interaction, 成員: discord.Member):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        if 成員.id == interaction.user.id:
            await interaction.response.send_message('❌ 你不能封鎖自己。', ephemeral=True)
            return
        if 成員.guild_permissions.administrator:
            await interaction.response.send_message('❌ 無法封鎖擁有管理員權限的使用者。', ephemeral=True)
            return

        db.add_to_blacklist(guild_id, channel_id, 成員.id)
        name = db.get_display_name(guild_id, 成員.id, fallback=成員.display_name)
        await interaction.response.send_message(
            f'🚫 已將 **{name}** 加入 **#{interaction.channel.name}** 的黑名單。\n'
            f'該成員將無法在此頻道簽到，且不計入統計。',
            ephemeral=True
        )

    @app_commands.command(name='解除黑名單', description='解除指定成員在此頻道的黑名單')
    @app_commands.describe(成員='要解除黑名單的成員')
    @admin_only()
    async def slash_blacklist_remove(self, interaction: discord.Interaction, 成員: discord.Member):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        success = db.remove_from_blacklist(guild_id, channel_id, 成員.id)
        name = db.get_display_name(guild_id, 成員.id, fallback=成員.display_name)
        if success:
            await interaction.response.send_message(
                f'✅ 已將 **{name}** 從黑名單中移除。', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f'⚠️ **{name}** 不在 **#{interaction.channel.name}** 的黑名單中。', ephemeral=True
            )

    @app_commands.command(name='查看黑名單', description='查看此頻道的黑名單')
    @admin_only()
    async def slash_blacklist_list(self, interaction: discord.Interaction):
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        bl = db.get_blacklist(guild_id, channel_id)
        embed = discord.Embed(title=f'🚫 黑名單 — #{interaction.channel.name}', color=0xED4245)

        if not bl:
            embed.description = '此頻道目前沒有任何黑名單成員。'
        else:
            lines = []
            for uid in bl:
                name = db.get_display_name(guild_id, uid, fallback=f'ID: {uid}')
                m = interaction.guild.get_member(int(uid))
                mention = m.mention if m else f'`{uid}`'
                lines.append(f'• {name} ({mention})')
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'共 {len(bl)} 位成員被封鎖')

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Blacklist(bot))
