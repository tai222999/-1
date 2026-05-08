import discord
from discord import app_commands
from discord.ext import commands


class Manual(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='指令說明', description='查看所有可用指令（只有你看得到）')
    async def slash_manual(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='📋 簽到機器人指令說明',
            color=0x5865F2,
            description='所有回應只有你自己看得到 👁️'
        )

        embed.add_field(
            name='👤 所有成員可使用',
            value=(
                '`/簽到` — 每日簽到（可附留言）\n'
                '`/今日簽到` — 查看今天已簽到的成員\n'
                '`/簽到排行` — 總簽到次數排行榜\n'
                '`/連續簽到排行` — 連續簽到天數排行榜\n'
                '`/未簽到排行` — 未簽到次數排行榜\n'
                '`/重置資訊` — 查看頻道重置時間與時區\n'
                '`/指令說明` — 顯示此說明\n\n'
                '💡 **或點擊管理員發布的簽到面板按鈕**'
            ),
            inline=False
        )

        embed.add_field(
            name='🔧 僅限管理員',
            value=(
                '`/發布面板` — 在此頻道發布簽到面板（含按鈕）\n'
                '`/設定暱稱` — 設定成員的顯示名稱\n'
                '`/調整簽到` — 增減指定成員的簽到次數\n'
                '`/批次調整簽到` — 一鍵調整頻道所有成員簽到次數\n'
                '`/調整未簽到` — 增減指定成員的未簽到次數\n'
                '`/設定重置時間` — 設定每日簽到重置時間（預設 23:59）\n'
                '`/切換截圖要求` — 開關截圖證明要求\n'
                '`/設定最少字數` — 設定簽到訊息最少字數\n'
                '`/切換每日公告` — 開關每日簽到統計公告\n'
                '`/新增簽到頻道` — 新增允許簽到的頻道\n'
                '`/移除簽到頻道` — 移除簽到頻道\n'
                '`/簽到頻道清單` — 查看所有簽到頻道\n'
                '`/清除頻道限制` — 清除限制（所有頻道皆可簽到）\n'
                '`/加入黑名單` — 禁止指定成員簽到\n'
                '`/解除黑名單` — 解除指定成員的黑名單\n'
                '`/查看黑名單` — 查看此頻道黑名單\n'
                '`/新增機器人管理員` — 授予機器人管理員權限\n'
                '`/移除機器人管理員` — 撤銷機器人管理員權限\n'
                '`/管理員清單` — 查看機器人管理員清單\n'
                '`/設定時區` — 設定伺服器時區\n'
                '`/重置排行榜` — 重置簽到或未簽到排行榜'
            ),
            inline=False
        )

        embed.set_footer(text='✅ 簽到機器人 | 使用 /指令說明 可隨時查看')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Manual(bot))
