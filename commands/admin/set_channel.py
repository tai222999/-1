import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class SetChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='新增簽到頻道', description='新增允許成員簽到的頻道（不設定則全部頻道皆可）')
    @app_commands.describe(頻道='要設定為簽到頻道的文字頻道（預設為目前頻道）')
    @admin_only()
    async def slash_add_channel(self, interaction: discord.Interaction,
                                 頻道: discord.TextChannel = None):
        db = self.bot.db
        target = 頻道 or interaction.channel
        db.add_checkin_channel(interaction.guild_id, target.id)
        await interaction.response.send_message(
            f'✅ 已將 {target.mention} 設定為簽到頻道。\n'
            f'只有已設定的頻道才能使用 `/簽到` 或面板按鈕。',
            ephemeral=True
        )

    @app_commands.command(name='移除簽到頻道', description='移除指定的簽到頻道')
    @app_commands.describe(頻道='要移除的簽到頻道（預設為目前頻道）')
    @admin_only()
    async def slash_remove_channel(self, interaction: discord.Interaction,
                                    頻道: discord.TextChannel = None):
        db = self.bot.db
        target = 頻道 or interaction.channel
        success = db.remove_checkin_channel(interaction.guild_id, target.id)

        if success:
            channels = db.get_checkin_channels(interaction.guild_id)
            if not channels:
                await interaction.response.send_message(
                    f'✅ 已移除 {target.mention} 的簽到限制。\n'
                    f'⚠️ 目前沒有設定任何簽到頻道，**所有頻道**都可以簽到。',
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f'✅ 已將 {target.mention} 從簽到頻道中移除。', ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f'⚠️ {target.mention} 本來就不在簽到頻道清單中。', ephemeral=True
            )

    @app_commands.command(name='簽到頻道清單', description='查看目前所有允許簽到的頻道')
    @admin_only()
    async def slash_list_channels(self, interaction: discord.Interaction):
        db = self.bot.db
        channels = db.get_checkin_channels(interaction.guild_id)
        embed = discord.Embed(title='📌 簽到頻道設定', color=0x5865F2)

        if not channels:
            embed.description = (
                '目前**沒有限制**簽到頻道，所有頻道都可以簽到。\n\n'
                '使用 `/新增簽到頻道` 來指定允許簽到的頻道。'
            )
        else:
            lines = []
            for cid in channels:
                ch = interaction.guild.get_channel(int(cid))
                lines.append(f'• {ch.mention}' if ch else f'• `已刪除的頻道 ({cid})`')
            embed.description = '\n'.join(lines)
            embed.set_footer(text=f'共 {len(channels)} 個簽到頻道')

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='清除頻道限制', description='清除所有簽到頻道限制，讓所有頻道都可以簽到')
    @admin_only()
    async def slash_clear_channels(self, interaction: discord.Interaction):
        db = self.bot.db
        gs = db.get_guild_settings(interaction.guild_id)
        gs['checkin_channels'] = []
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            '✅ 已清除所有簽到頻道限制，**所有頻道**都可以簽到。', ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(SetChannel(bot))
