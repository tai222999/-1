import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class Adjust(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /調整簽到 ────────────────────────────────────────────────
    @app_commands.command(name='調整簽到', description='增減指定成員的簽到次數（負數為減少）')
    @app_commands.describe(成員='要調整的成員', 數量='調整數量（正數增加，負數減少）')
    @admin_only()
    async def slash_adjust(self, interaction: discord.Interaction,
                            成員: discord.Member, 數量: int):
        db = self.bot.db
        guild_id = interaction.guild_id

        db.init_user(guild_id, 成員.id, 成員.display_name)
        db.adjust_total(guild_id, 成員.id, 數量)
        user_data = db.get_user_checkin(guild_id, 成員.id)
        new_total = user_data.get('total', 0)
        name = db.get_display_name(guild_id, 成員.id)
        sign = '+' if 數量 >= 0 else ''

        await interaction.response.send_message(
            f'✅ 已調整 **{name}** 的簽到次數：`{sign}{數量}` → 目前共 **{new_total}** 次',
            ephemeral=True
        )

    # ── /批次調整簽到 ────────────────────────────────────────────
    @app_commands.command(name='批次調整簽到', description='一鍵幫此頻道所有可見成員增減簽到次數')
    @app_commands.describe(數量='調整數量（正數增加，負數減少）')
    @admin_only()
    async def slash_batch_adjust(self, interaction: discord.Interaction, 數量: int):
        await interaction.response.defer(ephemeral=True)
        db         = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id

        affected = 0
        skipped  = 0
        for member in interaction.guild.members:
            if member.bot:
                continue
            if not interaction.channel.permissions_for(member).view_channel:
                continue
            if db.is_blacklisted(guild_id, channel_id, member.id):
                skipped += 1
                continue
            db.init_user(guild_id, member.id, member.display_name)
            db.adjust_total(guild_id, member.id, 數量)
            affected += 1

        sign = '+' if 數量 >= 0 else ''
        await interaction.followup.send(
            f'✅ 已批次調整 **{affected}** 位成員的簽到次數：`{sign}{數量}`\n'
            f'（黑名單 {skipped} 位已跳過）',
            ephemeral=True
        )

    # ── /調整未簽到 ──────────────────────────────────────────────
    @app_commands.command(name='調整未簽到', description='增減指定成員的未簽到次數（負數為減少）')
    @app_commands.describe(成員='要調整的成員', 數量='調整數量（正數增加，負數減少）')
    @admin_only()
    async def slash_adjust_miss(self, interaction: discord.Interaction,
                                 成員: discord.Member, 數量: int):
        db = self.bot.db
        guild_id = interaction.guild_id

        db.init_user(guild_id, 成員.id, 成員.display_name)
        db.adjust_miss(guild_id, 成員.id, 數量)
        user_data = db.get_user_checkin(guild_id, 成員.id)
        new_miss  = user_data.get('miss', 0)
        name = db.get_display_name(guild_id, 成員.id)
        sign = '+' if 數量 >= 0 else ''

        await interaction.response.send_message(
            f'✅ 已調整 **{name}** 的未簽到次數：`{sign}{數量}` → 目前共 **{new_miss}** 次',
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Adjust(bot))
