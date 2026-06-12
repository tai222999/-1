import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio


class DailyScheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.announced = set()
        self.daily_check.start()

    def cog_unload(self):
        self.daily_check.cancel()

    @tasks.loop(seconds=30)
    async def daily_check(self):
        db = self.bot.db
        from utils.database import _load, _save
        ch_settings = _load('channel_settings.json')

        for guild in self.bot.guilds:
            guild_id = guild.id
            now = db.get_now(guild_id)
            guild_channels = ch_settings.get(str(guild_id), {})

            for channel_id_str, settings in guild_channels.items():
                # 跳過已關閉每日公告的頻道（預設開啟）
                if not settings.get('announce_enabled', True):
                    continue

                reset_hour   = settings.get('reset_hour', 0)
                reset_minute = settings.get('reset_minute', 0)

                now_total   = now.hour * 60 + now.minute
                reset_total = reset_hour * 60 + reset_minute

                if now_total >= reset_total:
                    checkin_date_str = now.strftime('%Y-%m-%d')
                else:
                    yesterday = now - timedelta(days=1)
                    checkin_date_str = yesterday.strftime('%Y-%m-%d')

                announce_key = (guild_id, int(channel_id_str), checkin_date_str)

                is_reset_time      = (now.hour == reset_hour and now.minute == reset_minute)
                is_past_reset      = now_total > reset_total
                is_next_day_makeup = now_total < reset_total

                should_announce = (
                    (is_reset_time or is_past_reset or is_next_day_makeup) and
                    announce_key not in self.announced
                )

                if not should_announce:
                    continue

                # 持久化防重複
                announced_log = _load('announced_log.json')
                log_key = f'{guild_id}_{channel_id_str}_{checkin_date_str}'
                if announced_log.get(log_key):
                    self.announced.add(announce_key)
                    continue

                self.announced.add(announce_key)
                announced_log[log_key] = now.strftime('%Y-%m-%d %H:%M')
                _save('announced_log.json', announced_log)

                channel = guild.get_channel(int(channel_id_str))
                if channel:
                    is_makeup = not is_reset_time
                    await self._do_daily_reset(
                        guild, channel, settings, db,
                        checkin_date_str, reset_hour, reset_minute, is_makeup
                    )

    @daily_check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

    async def _do_daily_reset(self, guild, channel, settings, db,
                               checkin_date_str, reset_hour, reset_minute, is_makeup=False):
        guild_id   = guild.id
        channel_id = channel.id

        signed_ids = set(db.get_today_checkins(guild_id, channel_id, checkin_date_str))

        visible_members = [
            m for m in guild.members
            if not m.bot
            and channel.permissions_for(m).view_channel
            and not db.is_blacklisted(guild_id, channel_id, m.id)
        ]

        signed_members   = []
        unsigned_members = []

        for member in visible_members:
            uid  = str(member.id)
            name = db.get_display_name(guild_id, member.id, fallback=member.display_name)
            if uid in signed_ids:
                signed_members.append(name)
            else:
                unsigned_members.append((member, name))

        # 更新未簽到統計
        for member, name in unsigned_members:
            user_data = db.get_user_checkin(guild_id, member.id)
            if not user_data:
                user_data = db.init_user(guild_id, member.id, name)

            if user_data.get('last_miss') == checkin_date_str:
                continue
            if user_data.get('last_checkin') == checkin_date_str:
                continue

            user_data['miss'] = user_data.get('miss', 0) + 1

            last_miss = user_data.get('last_miss')
            if last_miss:
                diff = (
                    datetime.strptime(checkin_date_str, '%Y-%m-%d').date() -
                    datetime.strptime(last_miss, '%Y-%m-%d').date()
                ).days
                user_data['miss_streak'] = (user_data.get('miss_streak', 0) + 1) if diff == 1 else 1
            else:
                user_data['miss_streak'] = 1

            user_data['max_miss_streak'] = max(
                user_data.get('max_miss_streak', 0), user_data['miss_streak']
            )
            user_data['last_miss'] = checkin_date_str
            db.save_user_checkin(guild_id, member.id, user_data)

        # 發送公告
        tz_name = db.get_timezone(guild_id)
        title = f'📋 {checkin_date_str} 簽到日報'
        if is_makeup:
            title += '（補發）'

        embed = discord.Embed(
            title=title,
            color=0x5865F2,
            description=f'重置時間：{reset_hour:02d}:{reset_minute:02d}（{tz_name}）'
                        + ('\n⚠️ 此公告因 Bot 重啟而延遲發出' if is_makeup else '')
        )

        signed_text = '\n'.join(f'✅ {n}' for n in signed_members) or '今天沒有人簽到'
        if len(signed_text) > 1024:
            signed_text = signed_text[:1000] + '\n...'
        embed.add_field(name=f'📗 已簽到（{len(signed_members)} 人）', value=signed_text, inline=False)

        unsigned_text = '\n'.join(f'❌ {n}' for _, n in unsigned_members) or '所有人都簽到了！🎉'
        if len(unsigned_text) > 1024:
            unsigned_text = unsigned_text[:1000] + '\n...'
        embed.add_field(name=f'📕 未簽到（{len(unsigned_members)} 人）', value=unsigned_text, inline=False)

        total_visible = len(visible_members)
        rate = round(len(signed_members) / total_visible * 100) if total_visible else 0
        embed.set_footer(
            text=f'簽到率：{len(signed_members)}/{total_visible}（{rate}%）｜統計對象：可見頻道的成員'
        )

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f'[排程] 無法發送至頻道 {channel.id}：{e}')


async def setup(bot):
    await bot.add_cog(DailyScheduler(bot))
