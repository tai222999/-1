import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_welcome_settings(self, guild_id):
        gs = self.bot.db.get_guild_settings(guild_id)
        return {
            'welcome_channel': gs.get('welcome_channel'),
            'notice_channel': gs.get('notice_channel'),
        }

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = self.bot.db
        guild = member.guild
        ws = self._get_welcome_settings(guild.id)

        channel_id = ws.get('welcome_channel')
        if not channel_id:
            return

        channel = guild.get_channel(int(channel_id))
        if not channel:
            return

        notice_channel_id = ws.get('notice_channel')
        if notice_channel_id:
            notice_ch = guild.get_channel(int(notice_channel_id))
            notice_mention = notice_ch.mention if notice_ch else '📋 加入須知'
        else:
            notice_mention = '📋 加入須知'

        member_count = guild.member_count

        embed = discord.Embed(
            title=f'✨ 歡迎加入 {guild.name}！',
            color=0x57F287
        )
        embed.description = (
            f'哈囉！{member.mention}\n'
            f'務必請先閱讀 {notice_mention} ！\n\n'
            f'閱讀完後點擊下方表情符號即可查看其他頻道！\n'
            f'別忘記把自己的群組暱稱改為遊戲ID！\n\n'
            f'目前公會成員數量：**{member_count}**'
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        await channel.send(embed=embed)

    @app_commands.command(name='設定歡迎頻道', description='設定新成員加入時發送歡迎訊息的頻道')
    @app_commands.describe(頻道='要接收歡迎訊息的文字頻道（預設為目前頻道）')
    @admin_only()
    async def slash_set_welcome_channel(self, interaction: discord.Interaction,
                                        頻道: discord.TextChannel = None):
        db = self.bot.db
        target = 頻道 or interaction.channel
        gs = db.get_guild_settings(interaction.guild_id)
        gs['welcome_channel'] = str(target.id)
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 歡迎訊息頻道已設定為 {target.mention}。\n'
            f'新成員加入時，Bot 將在此頻道發送歡迎訊息。',
            ephemeral=True
        )

    @app_commands.command(name='設定須知頻道', description='設定歡迎訊息中連結的「加入須知」頻道')
    @app_commands.describe(頻道='要作為加入須知的文字頻道（預設為目前頻道）')
    @admin_only()
    async def slash_set_notice_channel(self, interaction: discord.Interaction,
                                       頻道: discord.TextChannel = None):
        db = self.bot.db
        target = 頻道 or interaction.channel
        gs = db.get_guild_settings(interaction.guild_id)
        gs['notice_channel'] = str(target.id)
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 加入須知頻道已設定為 {target.mention}。\n'
            f'歡迎訊息中將自動連結此頻道。',
            ephemeral=True
        )

    @app_commands.command(name='關閉歡迎訊息', description='關閉新成員加入的歡迎訊息')
    @admin_only()
    async def slash_disable_welcome(self, interaction: discord.Interaction):
        db = self.bot.db
        gs = db.get_guild_settings(interaction.guild_id)
        gs.pop('welcome_channel', None)
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            '✅ 歡迎訊息已關閉。新成員加入時將不會收到歡迎訊息。',
            ephemeral=True
        )

    @app_commands.command(name='測試歡迎訊息', description='模擬一次歡迎訊息，確認內容是否正確')
    @admin_only()
    async def slash_test_welcome(self, interaction: discord.Interaction):
        db = self.bot.db
        guild = interaction.guild
        ws = self._get_welcome_settings(guild.id)

        channel_id = ws.get('welcome_channel')
        if not channel_id:
            await interaction.response.send_message(
                '❌ 尚未設定歡迎頻道，請先使用 `/設定歡迎頻道`。',
                ephemeral=True
            )
            return

        channel = guild.get_channel(int(channel_id))
        if not channel:
            await interaction.response.send_message(
                '❌ 找不到設定的歡迎頻道，請重新設定。',
                ephemeral=True
            )
            return

        notice_channel_id = ws.get('notice_channel')
        if notice_channel_id:
            notice_ch = guild.get_channel(int(notice_channel_id))
            notice_mention = notice_ch.mention if notice_ch else '📋 加入須知'
        else:
            notice_mention = '📋 加入須知'

        member = interaction.user
        member_count = guild.member_count

        embed = discord.Embed(
            title=f'✨ 歡迎加入 {guild.name}！',
            color=0x57F287
        )
        embed.description = (
            f'哈囉！{member.mention}\n'
            f'務必請先閱讀 {notice_mention} ！\n\n'
            f'閱讀完後點擊下方表情符號即可查看其他頻道！\n'
            f'別忘記把自己的群組暱稱改為遊戲ID！\n\n'
            f'目前公會成員數量：**{member_count}**'
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.set_footer(text='⚠️ 這是測試訊息')

        await channel.send(embed=embed)
        await interaction.response.send_message(
            f'✅ 已在 {channel.mention} 發送測試歡迎訊息。',
            ephemeral=True
        )

    @app_commands.command(name='歡迎設定查看', description='查看目前的歡迎訊息設定')
    @admin_only()
    async def slash_welcome_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        ws = self._get_welcome_settings(guild.id)

        welcome_ch_id = ws.get('welcome_channel')
        notice_ch_id = ws.get('notice_channel')

        welcome_ch = guild.get_channel(int(welcome_ch_id)) if welcome_ch_id else None
        notice_ch = guild.get_channel(int(notice_ch_id)) if notice_ch_id else None

        embed = discord.Embed(title='🎉 歡迎訊息設定', color=0x5865F2)
        embed.add_field(
            name='歡迎頻道',
            value=welcome_ch.mention if welcome_ch else '❌ 未設定',
            inline=False
        )
        embed.add_field(
            name='加入須知頻道',
            value=notice_ch.mention if notice_ch else '❌ 未設定',
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
