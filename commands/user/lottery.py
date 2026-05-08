import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

TW_TZ = timezone(timedelta(hours=8))

def tw_now() -> datetime:
    return datetime.now(TW_TZ)

# 模組層級儲存（重啟後清空，符合抽籤的臨時性質）
active_lotteries: dict[int, dict[str, dict]] = {}   # {guild_id: {key: {...}}}
scheduled_tasks:  dict[str, dict]            = {}   # {"gid-key": {...}}


# ── 更新 Embed 成員列表（共用）────────────────────────────────────

async def _update_member_embed(interaction: discord.Interaction, lottery: dict):
    total = len(lottery['participants'])
    if total == 0:
        member_list = '尚未加入任何成員'
    elif total <= 30:
        member_list = '\n'.join(
            f'│`{i+1:>2}.` {m.display_name}'
            for i, m in enumerate(lottery['participants'])
        )
    else:
        first = '\n'.join(
            f'│`{i+1:>2}.` {m.display_name}'
            for i, m in enumerate(lottery['participants'][:10])
        )
        last = '\n'.join(
            f'│`{i+1:>2}.` {m.display_name}'
            for i, m in enumerate(lottery['participants'][-5:], total - 4)
        )
        member_list = f'{first}\n│... 共 {total} 人 ...\n{last}'

    embed = interaction.message.embeds[0]
    for i, field in enumerate(embed.fields):
        if '已加入成員' in field.name:
            embed.set_field_at(
                i,
                name=f'👥 已加入成員（共 {total} 人）',
                value=member_list[:1024],
                inline=False,
            )
            break
    await interaction.response.edit_message(embed=embed)


# ── 成員手動選擇 ──────────────────────────────────────────────────

class MemberSelect(ui.UserSelect):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(
            placeholder='👤 手動選擇成員...',
            min_values=1, max_values=25, row=0,
        )
        self.lottery_key = lottery_key
        self.guild_id    = guild_id

    async def callback(self, interaction: discord.Interaction):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True)
            return
        if interaction.user.id != lottery['creator']:
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True)
            return

        existing = {m.id for m in lottery['participants']}
        added = [m for m in self.values if m.id not in existing and not m.bot]
        if not added:
            await interaction.response.send_message('⚠️ 所選成員已在名單中或為機器人。', ephemeral=True)
            return
        lottery['participants'].extend(added)
        await _update_member_embed(interaction, lottery)


# ── 身份組批量加入 ────────────────────────────────────────────────

class RoleSelect(ui.RoleSelect):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(
            placeholder='🏷️ 選擇身份組（整組加入）...',
            min_values=1, max_values=10, row=1,
        )
        self.lottery_key = lottery_key
        self.guild_id    = guild_id

    async def callback(self, interaction: discord.Interaction):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True)
            return
        if interaction.user.id != lottery['creator']:
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True)
            return

        existing = {m.id for m in lottery['participants']}
        added = []
        for role in self.values:
            for member in role.members:
                if member.id not in existing and not member.bot:
                    lottery['participants'].append(member)
                    existing.add(member.id)
                    added.append(member)
        if not added:
            await interaction.response.send_message('⚠️ 該身份組的成員都已在名單中。', ephemeral=True)
            return
        await _update_member_embed(interaction, lottery)


# ── 抽籤管理面板（建立後顯示的操作介面）─────────────────────────

class LotteryManageView(ui.View):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(timeout=None)
        self.lottery_key = lottery_key
        self.guild_id    = guild_id
        self.add_item(MemberSelect(lottery_key, guild_id))
        self.add_item(RoleSelect(lottery_key, guild_id))

    def _get_lottery(self):
        return active_lotteries.get(self.guild_id, {}).get(self.lottery_key)

    def _check_creator(self, interaction: discord.Interaction) -> bool:
        lottery = self._get_lottery()
        return lottery and interaction.user.id == lottery['creator']

    # ── 加入頻道全員 ──────────────────────────────────────────────
    @ui.button(label='🟢 加入頻道全員', style=discord.ButtonStyle.primary, row=2)
    async def add_channel_members(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery()
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True); return
        if not self._check_creator(interaction):
            await interaction.response.send_message('❌ 只有建立者可以操作。', ephemeral=True); return

        existing = {m.id for m in lottery['participants']}
        added = [m for m in interaction.channel.members if m.id not in existing and not m.bot]
        if not added:
            await interaction.response.send_message('⚠️ 頻道內所有成員都已在名單中。', ephemeral=True); return
        lottery['participants'].extend(added)
        await _update_member_embed(interaction, lottery)

    # ── 開始抽籤 ──────────────────────────────────────────────────
    @ui.button(label='🎲 開始抽籤', style=discord.ButtonStyle.success, row=3)
    async def draw_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery()
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True); return
        if not self._check_creator(interaction):
            await interaction.response.send_message('❌ 只有建立者可以抽籤。', ephemeral=True); return

        participants  = lottery['participants']
        winner_count  = lottery['winner_count']

        if not participants:
            await interaction.response.send_message('❌ 尚未加入任何參加成員！', ephemeral=True); return
        if len(participants) < winner_count:
            await interaction.response.send_message(
                f'❌ 參加人數（{len(participants)}）少於中籤人數（{winner_count}），請增加成員。',
                ephemeral=True); return

        await interaction.response.send_message('🎲 正在抽籤中...', ephemeral=True)

        channel        = interaction.channel
        countdown_embed = discord.Embed(title=f'🎰 抽籤即將開始：{lottery["name"]}', color=0xFF6B6B)
        msg = await channel.send(embed=countdown_embed)

        for i in [3, 2, 1]:
            countdown_embed.description = f'# {i}'
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        winners = random.sample(participants, winner_count)

        result_embed = discord.Embed(
            title=f'🏆 抽籤結果：{lottery["name"]}',
            description=f'🎁 **獎品：**{lottery["prize"]}',
            color=0x00FF88,
            timestamp=tw_now(),
        )
        result_embed.add_field(
            name='🥇 中籤者',
            value='\n'.join(f'│🏆 **{i+1}.** {w.mention}' for i, w in enumerate(winners)),
            inline=False,
        )
        not_selected = [m for m in participants if m not in winners]
        if not_selected:
            result_embed.add_field(
                name='😢 未中籤',
                value=', '.join(m.display_name for m in not_selected)[:1024],
                inline=False,
            )
        result_embed.add_field(
            name='📊 統計',
            value=f'參加人數：{len(participants)} 人\n中籤人數：{winner_count} 人',
            inline=False,
        )
        result_embed.set_footer(text=f'由 {interaction.user.display_name} 抽籤')
        await msg.edit(embed=result_embed)
        await channel.send('🎉 恭喜中籤！' + ' '.join(w.mention for w in winners))

        task_key = f'{self.guild_id}-{self.lottery_key}'
        scheduled_tasks.pop(task_key, None)
        active_lotteries.get(self.guild_id, {}).pop(self.lottery_key, None)

    # ── 查看名單 ──────────────────────────────────────────────────
    @ui.button(label='📋 查看名單', style=discord.ButtonStyle.secondary, row=3)
    async def view_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery()
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True); return
        if not lottery['participants']:
            await interaction.response.send_message('📭 目前無加入成員。', ephemeral=True); return

        embed = discord.Embed(
            title=f'📋 {lottery["name"]} — 參加名單',
            description='\n'.join(
                f'│`{i+1:>2}.` {m.display_name} (`{m.id}`)'
                for i, m in enumerate(lottery['participants'])
            )[:4096],
            color=0x5865F2,
        )
        embed.set_footer(text=f'共 {len(lottery["participants"])} 人')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── 清空名單 ──────────────────────────────────────────────────
    @ui.button(label='🗑️ 清空名單', style=discord.ButtonStyle.danger, row=4)
    async def clear_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery()
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True); return
        if not self._check_creator(interaction):
            await interaction.response.send_message('❌ 只有建立者可以清空名單。', ephemeral=True); return

        lottery['participants'] = []
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if '已加入成員' in field.name:
                embed.set_field_at(i, name='👥 已加入成員', value='尚未加入任何成員', inline=False)
                break
        await interaction.response.edit_message(embed=embed)

    # ── 取消抽籤 ──────────────────────────────────────────────────
    @ui.button(label='✖ 取消抽籤', style=discord.ButtonStyle.secondary, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = self._get_lottery()
        if not lottery:
            await interaction.response.send_message('❌ 找不到此抽籤活動。', ephemeral=True); return
        if not self._check_creator(interaction):
            await interaction.response.send_message('❌ 只有建立者可以取消。', ephemeral=True); return

        scheduled_tasks.pop(f'{self.guild_id}-{self.lottery_key}', None)
        active_lotteries.get(self.guild_id, {}).pop(self.lottery_key, None)

        embed = discord.Embed(
            title='✖ 抽籤已取消',
            description=f'「{lottery["name"]}」已被 {interaction.user.display_name} 取消。',
            color=0xFF0000,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── 建立抽籤表單 ──────────────────────────────────────────────────

class LotteryModal(ui.Modal, title='🎰 建立抽籤活動'):
    lottery_name = ui.TextInput(label='抽籤名稱', placeholder='例如：每週幸運抽籤',
                                required=True, max_length=50)
    prize        = ui.TextInput(label='獎品說明', placeholder='例如：Steam 遊戲序號 x1',
                                required=True, max_length=200)
    winner_count = ui.TextInput(label='中籤人數', placeholder='例如：3',
                                required=True, max_length=3)
    schedule_time = ui.TextInput(
        label='定時抽籤（台灣時間，選填）',
        placeholder='格式：2025-01-15 20:00（留空＝手動抽籤）',
        required=False, max_length=20,
    )
    description  = ui.TextInput(
        label='活動說明（選填）',
        style=discord.TextStyle.paragraph,
        placeholder='填寫抽籤的額外說明...',
        required=False, max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.winner_count.value)
            if count < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message('❌ 中籤人數必須是正整數！', ephemeral=True)
            return

        draw_time = None
        if self.schedule_time.value.strip():
            try:
                draw_time = datetime.strptime(
                    self.schedule_time.value.strip(), '%Y-%m-%d %H:%M'
                ).replace(tzinfo=TW_TZ)
                if draw_time <= tw_now():
                    await interaction.response.send_message('❌ 定時時間必須是未來的時間！', ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message(
                    '❌ 時間格式錯誤，請用：`2025-01-15 20:00`', ephemeral=True)
                return

        guild_id = interaction.guild_id
        active_lotteries.setdefault(guild_id, {})

        lottery_key = self.lottery_name.value
        active_lotteries[guild_id][lottery_key] = {
            'name':         self.lottery_name.value,
            'prize':        self.prize.value,
            'winner_count': count,
            'description':  self.description.value or '無',
            'participants': [],
            'creator':      interaction.user.id,
            'created_at':   tw_now(),
            'draw_time':    draw_time,
            'channel_id':   interaction.channel_id,
        }

        if draw_time:
            scheduled_tasks[f'{guild_id}-{lottery_key}'] = {
                'guild_id':    guild_id,
                'lottery_key': lottery_key,
                'channel_id':  interaction.channel_id,
                'draw_time':   draw_time,
            }

        time_str = draw_time.strftime('%Y-%m-%d %H:%M') if draw_time else '手動抽籤'
        embed = discord.Embed(
            title=f'🎰 抽籤活動：{self.lottery_name.value}',
            description='📋 以下為抽籤資訊，僅建立者可操作下方按鈕。',
            color=0xFFD700,
        )
        embed.add_field(name='🎁 獎品',    value=self.prize.value,     inline=True)
        embed.add_field(name='🥇 中籤人數', value=f'{count} 人',        inline=True)
        embed.add_field(name='⏰ 抽籤時間', value=time_str,             inline=True)
        if self.description.value:
            embed.add_field(name='📝 說明', value=self.description.value, inline=False)
        embed.add_field(name='👥 已加入成員', value='尚未加入任何成員', inline=False)
        embed.set_footer(text=f'建立者：{interaction.user.display_name}｜僅建立者可操作')

        await interaction.response.send_message(embed=embed, view=LotteryManageView(lottery_key, guild_id))


# ── 主控面板 ──────────────────────────────────────────────────────

class MainPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🎰 建立抽籤', style=discord.ButtonStyle.success, row=0)
    async def create_lottery(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(LotteryModal())

    @ui.button(label='📋 查看進行中', style=discord.ButtonStyle.primary, row=0)
    async def view_active(self, interaction: discord.Interaction, button: ui.Button):
        lotteries = active_lotteries.get(interaction.guild_id, {})
        if not lotteries:
            await interaction.response.send_message('📭 目前沒有進行中的抽籤活動。', ephemeral=True)
            return

        embed = discord.Embed(title='📋 進行中的抽籤活動', color=0x5865F2)
        for key, lottery in lotteries.items():
            time_str = lottery['draw_time'].strftime('%Y-%m-%d %H:%M') if lottery.get('draw_time') else '手動抽籤'
            embed.add_field(
                name=f'🎰 {lottery["name"]}',
                value=(
                    f'🎁 獎品：{lottery["prize"]}\n'
                    f'🥇 中籤人數：{lottery["winner_count"]}\n'
                    f'👥 已加入：{len(lottery["participants"])} 人\n'
                    f'⏰ 抽籤：{time_str}'
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label='❓ 使用說明', style=discord.ButtonStyle.secondary, row=0)
    async def help_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(title='🎲 抽籤機器人使用說明', color=0xFFD700)
        embed.add_field(name='🎰 /抽籤面板',  value='顯示主控面板（僅自己可見）', inline=False)
        embed.add_field(name='🎲 /建立抽籤',  value='填寫表單建立抽籤，可設定定時抽籤', inline=False)
        embed.add_field(name='⚡ /快速抽籤',  value='直接指定成員立即抽籤', inline=False)
        embed.add_field(
            name='📥 加入方式（三種）',
            value=(
                '👤 **手動選人** — 用下拉選單逐一選\n'
                '🏷️ **選身份組** — 整組成員一次加入\n'
                '🟢 **頻道全員** — 此頻道所有人加入'
            ),
            inline=False,
        )
        embed.add_field(
            name='⏰ 定時抽籤',
            value='建立時填入台灣時間\n格式：`2025-06-01 20:00`\n時間到自動在頻道抽籤',
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────

class LotteryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_scheduled.start()

    def cog_unload(self):
        self.check_scheduled.cancel()

    @tasks.loop(seconds=30)
    async def check_scheduled(self):
        now = tw_now()
        to_remove = []

        for task_key, task_info in list(scheduled_tasks.items()):
            if now < task_info['draw_time']:
                continue
            to_remove.append(task_key)

            guild_id    = task_info['guild_id']
            lottery_key = task_info['lottery_key']
            channel_id  = task_info['channel_id']

            lottery = active_lotteries.get(guild_id, {}).get(lottery_key)
            if not lottery:
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            participants = lottery['participants']
            winner_count = lottery['winner_count']

            if len(participants) < winner_count:
                await channel.send(
                    f'❌ 定時抽籤「{lottery["name"]}」參加人數不足（{len(participants)}/{winner_count}），已取消。'
                )
                active_lotteries.get(guild_id, {}).pop(lottery_key, None)
                continue

            countdown_embed = discord.Embed(
                title=f'⏰ 定時抽籤開始：{lottery["name"]}', color=0xFF6B6B
            )
            msg = await channel.send(embed=countdown_embed)
            for i in [3, 2, 1]:
                countdown_embed.description = f'# {i}'
                await msg.edit(embed=countdown_embed)
                await asyncio.sleep(1)

            winners = random.sample(participants, winner_count)
            result_embed = discord.Embed(
                title=f'🏆 抽籤結果：{lottery["name"]}',
                description=f'🎁 **獎品：**{lottery["prize"]}',
                color=0x00FF88,
                timestamp=tw_now(),
            )
            result_embed.add_field(
                name='🥇 中籤者',
                value='\n'.join(f'│🏆 **{i+1}.** {w.mention}' for i, w in enumerate(winners)),
                inline=False,
            )
            not_selected = [m for m in participants if m not in winners]
            if not_selected:
                result_embed.add_field(
                    name='😢 未中籤',
                    value=', '.join(m.display_name for m in not_selected)[:1024],
                    inline=False,
                )
            result_embed.add_field(
                name='📊 統計',
                value=f'參加人數：{len(participants)} 人\n中籤人數：{winner_count} 人',
                inline=False,
            )
            result_embed.set_footer(text='⏰ 定時自動抽籤')
            await msg.edit(embed=result_embed)
            await channel.send('🎉 恭喜中籤！' + ' '.join(w.mention for w in winners))
            active_lotteries.get(guild_id, {}).pop(lottery_key, None)

        for key in to_remove:
            scheduled_tasks.pop(key, None)

    @check_scheduled.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── /抽籤面板 ──────────────────────────────────────────────
    @app_commands.command(name='抽籤面板', description='🎰 顯示抽籤機器人主控面板')
    async def lottery_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='🎰 抽籤機器人',
            description='歡迎使用抽籤機器人！\n點擊下方按鈕開始操作。',
            color=0xFFD700,
        )
        embed.add_field(name='🎰 建立抽籤',  value='建立新的抽籤活動', inline=True)
        embed.add_field(name='📋 查看進行中', value='查看目前的抽籤',   inline=True)
        embed.add_field(name='❓ 使用說明',  value='查看指令教學',     inline=True)
        embed.set_footer(text='抽籤機器人｜公平公正公開 🎲')
        await interaction.response.send_message(embed=embed, view=MainPanelView(), ephemeral=True)

    # ── /建立抽籤 ──────────────────────────────────────────────
    @app_commands.command(name='建立抽籤', description='🎲 透過表單建立一個新的抽籤活動')
    async def create_lottery_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LotteryModal())

    # ── /快速抽籤 ──────────────────────────────────────────────
    @app_commands.command(name='快速抽籤', description='⚡ 從指定成員中快速抽籤')
    @app_commands.describe(
        中籤人數='要抽出幾位中籤者',
        獎品='獎品說明',
        成員1='參加者 1', 成員2='參加者 2', 成員3='參加者 3',
        成員4='參加者 4（選填）', 成員5='參加者 5（選填）',
        成員6='參加者 6（選填）', 成員7='參加者 7（選填）',
        成員8='參加者 8（選填）',
    )
    async def quick_draw(
        self, interaction: discord.Interaction,
        中籤人數: int, 獎品: str,
        成員1: discord.Member, 成員2: discord.Member, 成員3: discord.Member,
        成員4: Optional[discord.Member] = None, 成員5: Optional[discord.Member] = None,
        成員6: Optional[discord.Member] = None, 成員7: Optional[discord.Member] = None,
        成員8: Optional[discord.Member] = None,
    ):
        all_members  = [成員1, 成員2, 成員3, 成員4, 成員5, 成員6, 成員7, 成員8]
        participants = list({m for m in all_members if m is not None and not m.bot})

        if 中籤人數 < 1:
            await interaction.response.send_message('❌ 中籤人數至少為 1！', ephemeral=True); return
        if len(participants) < 中籤人數:
            await interaction.response.send_message(
                f'❌ 參加人數（{len(participants)}）不足，無法抽出 {中籤人數} 位中籤者。',
                ephemeral=True); return

        await interaction.response.defer()
        countdown_embed = discord.Embed(title='⚡ 快速抽籤即將開始...', color=0xFF6B6B)
        msg = await interaction.followup.send(embed=countdown_embed)

        for i in [3, 2, 1]:
            countdown_embed.description = f'# {i}'
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        winners = random.sample(participants, 中籤人數)
        result_embed = discord.Embed(
            title='🏆 快速抽籤結果',
            description=f'🎁 **獎品：**{獎品}',
            color=0x00FF88,
            timestamp=tw_now(),
        )
        result_embed.add_field(
            name='🥇 中籤者',
            value='\n'.join(f'│🏆 **{i+1}.** {w.mention}' for i, w in enumerate(winners)),
            inline=False,
        )
        result_embed.add_field(
            name='📊 參加名單',
            value=f'{", ".join(m.display_name for m in participants)}\n（共 {len(participants)} 人，抽 {中籤人數} 人）',
            inline=False,
        )
        result_embed.set_footer(text=f'由 {interaction.user.display_name} 抽籤')
        await msg.edit(embed=result_embed)
        await interaction.channel.send('🎉 恭喜中籤！' + ' '.join(w.mention for w in winners))


async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryCog(bot))
