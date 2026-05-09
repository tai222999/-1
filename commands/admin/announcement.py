import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import uuid
import calendar

from utils.database import _load, _save
from utils.helpers import admin_only

TW_TZ = timezone(timedelta(hours=8))

def tw_now() -> datetime:
    return datetime.now(TW_TZ)

ANNOUNCE_FILE = 'announcements.json'

FREQ_MAP = {
    '每時': 'hourly',
    '每日': 'daily',
    '每周': 'weekly',
    '每月': 'monthly',
}
FREQ_LABEL = {v: k for k, v in FREQ_MAP.items()}


# ── 工具函式 ──────────────────────────────────────────────────────

def _load_data() -> dict:
    return _load(ANNOUNCE_FILE)

def _save_data(data: dict):
    _save(ANNOUNCE_FILE, data)

def _store(guild_id: int, ann: dict):
    data = _load_data()
    gid  = str(guild_id)
    if gid not in data:
        data[gid] = {}
    data[gid][ann['id']] = ann
    _save_data(data)

def _calc_next(base: datetime, frequency: str) -> datetime | None:
    if frequency == 'hourly':
        return base + timedelta(hours=1)
    if frequency == 'daily':
        return base + timedelta(days=1)
    if frequency == 'weekly':
        return base + timedelta(weeks=1)
    if frequency == 'monthly':
        y, m = base.year, base.month + 1
        if m > 12:
            m, y = 1, y + 1
        d = min(base.day, calendar.monthrange(y, m)[1])
        return base.replace(year=y, month=m, day=d)
    return None

async def _do_send(channel: discord.TextChannel, ann: dict, guild: discord.Guild) -> bool:
    mention_str = ''
    allowed     = discord.AllowedMentions.none()
    if ann.get('mention_type') == 'everyone':
        mention_str = '@everyone'
        allowed     = discord.AllowedMentions(everyone=True)
    elif ann.get('mention_type') == 'role':
        role = discord.utils.find(lambda r: r.name == ann.get('mention_value', ''), guild.roles)
        if role:
            mention_str = role.mention
            allowed     = discord.AllowedMentions(roles=[role])

    freq      = ann.get('frequency', 'once')
    next_dt   = _calc_next(tw_now(), freq)
    freq_text = FREQ_LABEL.get(freq, '不重複')

    # Tag 放在內容下方（在 embed 內）
    description = ann['content']
    if mention_str:
        description += f'\n\n{mention_str}'

    embed = discord.Embed(
        title       = f'📢  {ann["title"]}',
        description = description,
        color       = 0x5865F2,
        timestamp   = tw_now(),
    )

    # 發布者顯示為 mention（在 embed field 內才能渲染為可點擊）
    creator_id = ann.get('created_by')
    if creator_id:
        embed.add_field(name='發布者', value=f'<@{creator_id}>', inline=True)

    if freq != 'once' and next_dt:
        embed.set_footer(
            text=f'🔄 自動重複：{freq_text}  ｜  下次：{next_dt.strftime("%Y-%m-%d %H:%M")} 台北時間'
        )

    try:
        # content 只放 mention（觸發 ping），不含其他文字
        await channel.send(
            content          = mention_str or None,
            embed            = embed,
            allowed_mentions = allowed,
        )
        return True
    except Exception:
        return False


# ── 公告表單 ──────────────────────────────────────────────────────

class AnnouncementModal(ui.Modal, title='📢 建立公告'):
    ann_title = ui.TextInput(
        label       = '公告標題',
        placeholder = '例如：本週例行活動公告',
        required    = True, max_length=100,
    )
    content = ui.TextInput(
        label       = '公告內容',
        style       = discord.TextStyle.paragraph,
        placeholder = '在此填寫公告的詳細內容…',
        required    = True, max_length=2000,
    )
    mention = ui.TextInput(
        label       = '標記（選填）',
        placeholder = 'everyone  /  身份組名稱  /  留空不標記',
        required    = False, max_length=100,
    )
    frequency = ui.TextInput(
        label       = '重複週期（選填）',
        placeholder = '每時 / 每日 / 每周 / 每月 / 留空=不重複',
        required    = False, max_length=10,
    )
    schedule_time = ui.TextInput(
        label       = '首次發布時間（台灣時間，選填）',
        placeholder = '格式：2026-05-10 20:00    留空 = 立即發布',
        required    = False, max_length=20,
    )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback
        traceback.print_exc()
        try:
            await interaction.response.send_message(f'❌ 發生錯誤：{error}', ephemeral=True)
        except Exception:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        # ─ 解析頻率 ─
        frequency = FREQ_MAP.get(self.frequency.value.strip(), 'once')

        # ─ 解析時間 ─
        first_run = None
        if self.schedule_time.value.strip():
            try:
                first_run = datetime.strptime(
                    self.schedule_time.value.strip(), '%Y-%m-%d %H:%M'
                ).replace(tzinfo=TW_TZ)
                if first_run <= tw_now():
                    await interaction.response.send_message(
                        '❌ 發布時間必須是未來！', ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message(
                    '❌ 時間格式錯誤，請填：`2026-05-10 20:00`', ephemeral=True)
                return

        # ─ 取得公告頻道 ─
        gs    = interaction.client.db.get_guild_settings(interaction.guild_id)
        ch_id = gs.get('announcement_channel')
        if not ch_id:
            await interaction.response.send_message(
                '❌ 尚未設定公告發布頻道！請先使用 `/設定公告發布頻道`。', ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message(
                '❌ 找不到公告頻道，請重新設定。', ephemeral=True)
            return

        # ─ 解析 mention ─
        mention_input = self.mention.value.strip()
        mention_type  = 'none'
        if mention_input.lower() in ('everyone', '@everyone'):
            mention_type = 'everyone'
        elif mention_input:
            role = discord.utils.find(
                lambda r: r.name == mention_input, interaction.guild.roles)
            if not role:
                await interaction.response.send_message(
                    f'❌ 找不到身份組「{mention_input}」，請確認名稱正確。', ephemeral=True)
                return
            mention_type = 'role'

        ann = {
            'id':              str(uuid.uuid4())[:8].upper(),
            'title':           self.ann_title.value,
            'content':         self.content.value,
            'mention_type':    mention_type,
            'mention_value':   mention_input,
            'frequency':       frequency,
            'channel_id':      str(channel.id),
            'guild_id':        str(interaction.guild_id),
            'created_by':      str(interaction.user.id),
            'created_by_name': interaction.user.display_name,
            'created_at':      tw_now().isoformat(),
            'next_run':        (first_run or tw_now()).isoformat(),
        }

        freq_label = FREQ_LABEL.get(frequency, '不重複')

        if not first_run:
            ok = await _do_send(channel, ann, interaction.guild)
            if not ok:
                await interaction.response.send_message(
                    '❌ 發送失敗，請確認機器人有該頻道的發送權限。', ephemeral=True)
                return
            if frequency != 'once':
                next_dt      = _calc_next(tw_now(), frequency)
                ann['next_run'] = next_dt.isoformat()
                _store(interaction.guild_id, ann)
                await interaction.response.send_message(
                    f'✅ 公告已發布！\n🔄 下次自動重複：{next_dt.strftime("%Y-%m-%d %H:%M")}（{freq_label}）',
                    ephemeral=True)
            else:
                await interaction.response.send_message('✅ 公告已發布！', ephemeral=True)
        else:
            _store(interaction.guild_id, ann)
            await interaction.response.send_message(
                f'✅ 公告已排程！\n'
                f'📅 首次發布：{first_run.strftime("%Y-%m-%d %H:%M")} 台北時間\n'
                f'🔄 重複：{freq_label}',
                ephemeral=True)


# ── 刪除排程選單 ──────────────────────────────────────────────────

class AnnDeleteSelect(ui.Select):
    def __init__(self, gid: str, anns: dict):
        self.gid = gid
        options  = [
            discord.SelectOption(
                label       = ann['title'][:80],
                description = f'ID：{ann_id}  ｜  {FREQ_LABEL.get(ann["frequency"], "不重複")}',
                value       = ann_id,
            )
            for ann_id, ann in list(anns.items())[:25]
        ]
        super().__init__(placeholder='選擇要刪除的排程公告…', options=options,
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        data   = _load_data()
        ann_id = self.values[0]
        if ann_id not in data.get(self.gid, {}):
            await interaction.response.send_message('❌ 找不到此公告。', ephemeral=True)
            return
        title = data[self.gid][ann_id]['title']
        del data[self.gid][ann_id]
        _save_data(data)
        await interaction.response.send_message(
            f'✅ 已刪除排程公告：**{title}**（`{ann_id}`）', ephemeral=True)


class AnnDeleteView(ui.View):
    def __init__(self, gid: str, anns: dict):
        super().__init__(timeout=60)
        self.add_item(AnnDeleteSelect(gid, anns))


# ── 管理員操作面板（ephemeral）────────────────────────────────────

class AnnManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    def _ok(self, interaction: discord.Interaction) -> bool:
        return interaction.client.db.is_admin(interaction.guild_id, interaction.user)

    @ui.button(label='📢 發布公告', style=discord.ButtonStyle.success, row=0)
    async def post_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message('❌ 只有管理員可以操作。', ephemeral=True)
            return
        await interaction.response.send_modal(AnnouncementModal())

    @ui.button(label='📋 查看排程', style=discord.ButtonStyle.primary, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message('❌ 只有管理員可以操作。', ephemeral=True)
            return
        data = _load_data()
        gid  = str(interaction.guild_id)
        anns = data.get(gid, {})
        if not anns:
            await interaction.response.send_message('📭 目前沒有排程公告。', ephemeral=True)
            return
        embed = discord.Embed(title='📋 排程公告列表', color=0x5865F2)
        for ann_id, ann in anns.items():
            next_run = datetime.fromisoformat(ann['next_run']).strftime('%Y-%m-%d %H:%M')
            freq     = FREQ_LABEL.get(ann['frequency'], '不重複')
            embed.add_field(
                name   = f'`{ann_id}`  {ann["title"]}',
                value  = f'🔄 {freq}  ｜  ⏰ 下次：{next_run} 台北時間',
                inline = False,
            )
        embed.set_footer(text='點擊「🗑️ 刪除排程」可取消自動重複')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label='🗑️ 刪除排程', style=discord.ButtonStyle.danger, row=0)
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message('❌ 只有管理員可以操作。', ephemeral=True)
            return
        gid  = str(interaction.guild_id)
        data = _load_data()
        anns = data.get(gid, {})
        if not anns:
            await interaction.response.send_message('📭 沒有排程公告可刪除。', ephemeral=True)
            return
        await interaction.response.send_message(
            '請選擇要刪除的公告：', view=AnnDeleteView(gid, anns), ephemeral=True)


# ── 公告面板（持久化，公開，僅管理員可互動）──────────────────────

class AnnouncementPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='📢 公告管理', style=discord.ButtonStyle.primary,
               custom_id='ann_panel_open', row=0)
    async def open_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.client.db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 此功能僅限管理員使用。', ephemeral=True)
            return
        embed = discord.Embed(
            title       = '📢 公告管理系統',
            description = (
                '**📢 發布公告** — 填寫表單，立即或定時發布至公告頻道\n'
                '**📋 查看排程** — 查看所有自動重複的排程公告\n'
                '**🗑️ 刪除排程** — 取消指定的自動排程公告'
            ),
            color = 0x5865F2,
        )
        embed.set_footer(text='此面板僅你可見  ｜  管理員專用')
        await interaction.response.send_message(
            embed=embed, view=AnnManageView(), ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────

class AnnouncementCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AnnouncementPanelView())
        self.check_announcements.start()

    def cog_unload(self):
        self.check_announcements.cancel()

    # ── 定時發布排程 ──────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def check_announcements(self):
        now  = tw_now()
        data = _load_data()
        changed = False

        for gid, anns in data.items():
            for ann_id, ann in list(anns.items()):
                try:
                    if now < datetime.fromisoformat(ann['next_run']):
                        continue
                    guild = self.bot.get_guild(int(gid))
                    if not guild:
                        continue
                    channel = guild.get_channel(int(ann['channel_id']))
                    if not channel:
                        continue

                    await _do_send(channel, ann, guild)
                    changed = True

                    next_dt = _calc_next(now, ann['frequency'])
                    if next_dt:
                        ann['next_run'] = next_dt.isoformat()
                    else:
                        del anns[ann_id]
                except Exception as e:
                    print(f'[公告系統] 發送失敗 {ann_id}: {e}')

        if changed:
            _save_data(data)

    @check_announcements.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── /公告面板 ────────────────────────────────────────────────
    @app_commands.command(name='公告面板', description='在此頻道發布公告管理面板（僅限管理員）')
    @admin_only()
    async def ann_panel_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '📢 公告系統',
            description = (
                '管理員請點擊按鈕使用公告功能：\n\n'
                '• 立即發布或設定定時公告\n'
                '• 支援每時 / 每日 / 每周 / 每月自動重複\n'
                '• 可標記 @everyone 或指定身份組\n'
                '• 可隨時查看並刪除排程中的公告'
            ),
            color = 0x5865F2,
        )
        await interaction.response.send_message(embed=embed, view=AnnouncementPanelView())

    # ── /設定公告發布頻道 ────────────────────────────────────────
    @app_commands.command(name='設定公告發布頻道', description='設定公告內容發布的目標頻道（僅限管理員）')
    @app_commands.describe(頻道='公告將發布到此頻道')
    @admin_only()
    async def set_ann_ch(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['announcement_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 公告發布頻道已設定為 {頻道.mention}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnnouncementCog(bot))
