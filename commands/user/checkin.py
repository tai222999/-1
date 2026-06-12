import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime


class CheckIn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='簽到', description='每日簽到（只有你看得到結果）')
    @app_commands.describe(訊息='簽到留言（選填）')
    async def slash_checkin(self, interaction: discord.Interaction, 訊息: str = ''):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        guild_id   = interaction.guild_id
        channel_id = interaction.channel_id
        user       = interaction.user

        # 簽到頻道限制
        if not db.is_checkin_channel(guild_id, channel_id):
            allowed = db.get_checkin_channels(guild_id)
            mentions = [
                interaction.guild.get_channel(int(cid)).mention
                for cid in allowed
                if interaction.guild.get_channel(int(cid))
            ]
            mention_str = '、'.join(mentions) if mentions else '（無設定）'
            await interaction.followup.send(
                f'❌ 此頻道不開放簽到！\n請前往以下頻道進行簽到：{mention_str}',
                ephemeral=True
            )
            return

        # 黑名單
        if db.is_blacklisted(guild_id, channel_id, user.id):
            await interaction.followup.send('❌ 你已被加入黑名單，無法在此頻道簽到。', ephemeral=True)
            return

        # 頻道設定
        settings     = db.get_channel_settings(guild_id, channel_id)
        reset_hour   = settings.get('reset_hour', 0)
        reset_minute = settings.get('reset_minute', 0)
        require_proof = settings.get('require_proof', False)
        min_words    = settings.get('min_words', 0)

        if require_proof:
            await interaction.followup.send(
                '❌ 此頻道的簽到需要附上截圖！請改用頻道面板的 ✅ 簽到按鈕並同時在頻道傳送圖片。',
                ephemeral=True
            )
            return

        if min_words > 0 and len(訊息.strip()) < min_words:
            await interaction.followup.send(
                f'❌ 簽到訊息至少需要 **{min_words}** 個字！（目前：{len(訊息.strip())} 個字）',
                ephemeral=True
            )
            return

        today_str = db.get_today_str(guild_id, reset_hour, reset_minute)

        # 初始化使用者
        nickname = db.get_nickname(guild_id, user.id)
        display_name = nickname if nickname else (user.display_name or user.name)
        user_data = db.get_user_checkin(guild_id, user.id)
        if not user_data:
            user_data = db.init_user(guild_id, user.id, display_name)
        elif not nickname:
            user_data['display_name'] = display_name

        # 重複簽到
        if str(user.id) in db.get_today_checkins(guild_id, channel_id, today_str):
            await interaction.followup.send('⚠️ 你今天已經簽到過了！', ephemeral=True)
            return

        # 更新連續簽到
        last_checkin = user_data.get('last_checkin')
        if last_checkin:
            diff = (
                datetime.strptime(today_str, '%Y-%m-%d').date() -
                datetime.strptime(last_checkin, '%Y-%m-%d').date()
            ).days
            user_data['streak'] = (user_data.get('streak', 0) + 1) if diff == 1 else 1
        else:
            user_data['streak'] = 1

        user_data['max_streak'] = max(user_data.get('max_streak', 0), user_data['streak'])
        user_data['total']       = user_data.get('total', 0) + 1
        user_data['last_checkin'] = today_str
        user_data.setdefault('history', []).append(today_str)
        user_data['display_name'] = display_name

        db.save_user_checkin(guild_id, user.id, user_data)
        db.add_today_checkin(guild_id, channel_id, user.id, today_str)

        # 發放簽到幣
        new_coins = db.add_coins(guild_id, user.id, 1)

        streak = user_data['streak']
        total  = user_data['total']

        streak_emoji = ''
        if streak >= 30: streak_emoji = '🏆'
        elif streak >= 14: streak_emoji = '🔥'
        elif streak >= 7:  streak_emoji = '⚡'
        elif streak >= 3:  streak_emoji = '✨'

        embed = discord.Embed(title='✅ 簽到成功！', color=0x57F287)
        embed.set_author(name=display_name, icon_url=user.display_avatar.url)
        embed.description = (
            f'📅 日期：**{today_str}**\n'
            f'📊 總簽到：**{total}** 次\n'
            f'{streak_emoji} 連續簽到：**{streak}** 天\n'
            f'💰 獲得 1 枚簽到幣（共 **{new_coins}** 枚）'
        )
        if 訊息:
            embed.description += f'\n\n💬 留言：{訊息}'
        if streak >= 3:
            embed.set_footer(text=f'🎯 連續 {streak} 天，繼續加油！')

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CheckIn(bot))
