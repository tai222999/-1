import discord
from discord import app_commands
from discord.ext import commands
from utils.helpers import admin_only

DEFAULT_TEMPLATE = (
    '哈囉！{成員}\n'
    '務必請先閱讀 {須知} ！\n\n'
    '閱讀完後點擊下方表情符號即可查看其他頻道！\n'
    '別忘記把自己的群組暱稱改為遊戲ID！\n\n'
    '目前公會成員數量：**{人數}**'
)


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_welcome_settings(self, guild_id):
        gs = self.bot.db.get_guild_settings(guild_id)
        return {
            'welcome_channel': gs.get('welcome_channel'),
            'notice_channel': gs.get('notice_channel'),
            'welcome_template': gs.get('welcome_template', DEFAULT_TEMPLATE),
        }

    def _build_embed(self, guild, member, ws, *, is_test=False):
        notice_channel_id = ws.get('notice_channel')
        if notice_channel_id:
            notice_ch = guild.get_channel(int(notice_channel_id))
            notice_mention = notice_ch.mention if notice_ch else '📋 加入須知（請先用 /設定須知頻道 設定）'
        else:
            notice_mention = '📋 加入須知（請先用 /設定須知頻道 設定）'

        template = ws.get('welcome_template') or DEFAULT_TEMPLATE
        description = template.format(
            成員=member.mention,
            須知=notice_mention,
            人數=guild.member_count,
        )

        embed = discord.Embed(
            title=f'✨ 歡迎加入 {guild.name}！',
            description=description,
            color=0x57F287,
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        if is_test:
            embed.set_footer(text='⚠️ 這是測試訊息')
        return embed

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        ws = self._get_welcome_settings(guild.id)

        channel_id = ws.get('welcome_channel')
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return

        embed = self._build_embed(guild, member, ws)
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
            f'✅ 歡迎訊息頻道已設定為 {target.mention}。',
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
            f'✅ 加入須知頻道已設定為 {target.mention}，歡迎訊息將自動連結此頻道。',
            ephemeral=True
        )

    @app_commands.command(name='設定歡迎文字', description='自訂歡迎訊息的內文，可用 {成員} {須知} {人數} 作為變數')
    @app_commands.describe(內容='訊息內文，{成員}=新成員tag，{須知}=須知頻道tag，{人數}=目前人數')
    @admin_only()
    async def slash_set_welcome_text(self, interaction: discord.Interaction, 內容: str):
        db = self.bot.db
        gs = db.get_guild_settings(interaction.guild_id)
        gs['welcome_template'] = 內容
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 歡迎文字已更新：\n```\n{內容}\n```\n'
            f'可用變數：`{{成員}}` `{{須知}}` `{{人數}}`\n'
            f'使用 `/測試歡迎訊息` 預覽效果。',
            ephemeral=True
        )

    @app_commands.command(name='重設歡迎文字', description='將歡迎訊息內文還原為預設值')
    @admin_only()
    async def slash_reset_welcome_text(self, interaction: discord.Interaction):
        db = self.bot.db
        gs = db.get_guild_settings(interaction.guild_id)
        gs.pop('welcome_template', None)
        db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            '✅ 歡迎文字已還原為預設值。',
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
            '✅ 歡迎訊息已關閉。',
            ephemeral=True
        )

    @app_commands.command(name='測試歡迎訊息', description='模擬一次歡迎訊息，確認內容是否正確')
    @admin_only()
    async def slash_test_welcome(self, interaction: discord.Interaction):
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

        embed = self._build_embed(guild, interaction.user, ws, is_test=True)
        await channel.send(embed=embed)
        await interaction.response.send_message(
            f'✅ 已在 {channel.mention} 發送測試歡迎訊息。',
            ephemeral=True
        )

    @app_commands.command(name='歡迎設定查看', description='查看目前的歡迎訊息設定與文字內容')
    @admin_only()
    async def slash_welcome_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        ws = self._get_welcome_settings(guild.id)

        welcome_ch_id = ws.get('welcome_channel')
        notice_ch_id = ws.get('notice_channel')
        welcome_ch = guild.get_channel(int(welcome_ch_id)) if welcome_ch_id else None
        notice_ch = guild.get_channel(int(notice_ch_id)) if notice_ch_id else None
        template = ws.get('welcome_template') or DEFAULT_TEMPLATE

        embed = discord.Embed(title='🎉 歡迎訊息設定', color=0x5865F2)
        embed.add_field(
            name='歡迎頻道',
            value=welcome_ch.mention if welcome_ch else '❌ 未設定',
            inline=True
        )
        embed.add_field(
            name='加入須知頻道',
            value=notice_ch.mention if notice_ch else '❌ 未設定',
            inline=True
        )
        embed.add_field(
            name='訊息內文（可用 /設定歡迎文字 修改）',
            value=f'```\n{template}\n```',
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
