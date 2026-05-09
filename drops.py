import discord
from discord import app_commands, ui
from discord.ext import commands
import re

from utils.database import _load, _save
from utils.helpers import admin_only

DROPS_FILE = 'drops.json'


# ── 資料存取 ──────────────────────────────────────────────────────

def _load_drops() -> dict:
    data = _load(DROPS_FILE)
    return data if isinstance(data, dict) and 'monsters' in data else {'monsters': {}}

def _save_drops(data: dict):
    _save(DROPS_FILE, data)

def _parse_drop_file(text: str) -> dict:
    """解析怪物掉落文字檔。格式：LV.X怪物名稱 開頭，之後每行一個掉落物。"""
    monsters: dict = {}
    current_name:  str | None = None
    current_level: str = '?'
    current_drops: list = []

    def _flush():
        if current_name and current_drops:
            monsters[current_name] = {
                'name':       current_name,
                'level':      current_level,
                'drops':      sorted(set(current_drops)),
                'skillbooks': [],
                'recipes':    [],
            }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r'^LV\.(\d+)\s*(.+)$', line, re.IGNORECASE)
        if m:
            _flush()
            current_level = m.group(1)
            current_name  = m.group(2).strip()
            current_drops = []
        elif current_name:
            current_drops.append(line)

    _flush()
    return monsters

def _parse_items(raw: str) -> list:
    if not raw or not raw.strip():
        return []
    return [item.strip() for item in raw.split('、') if item.strip()]

def _search_monsters(data: dict, keyword: str) -> list:
    kw = keyword.strip().lower()
    return [m for m in data['monsters'].values() if kw in m['name'].lower()]

def _search_items(data: dict, keyword: str, category: str) -> list:
    kw = keyword.strip().lower()
    results = []
    for m in data['monsters'].values():
        matched = [i for i in m.get(category, []) if kw in i.lower()]
        if matched:
            results.append({'monster': m, 'matched': matched})
    return results

def _unique_items(results: list) -> list:
    """從搜尋結果中提取不重複的物品名稱清單。"""
    seen, items = set(), []
    for r in results:
        for item in r['matched']:
            if item not in seen:
                seen.add(item)
                items.append(item)
    return items


# ── Select 選單（精確選擇）────────────────────────────────────────

class MonsterResultSelect(ui.Select):
    def __init__(self, monsters: list):
        options = [
            discord.SelectOption(
                label       = f'{m["name"]}（Lv.{m["level"]}）'[:100],
                description = f'共 {len(m.get("drops",[]))+len(m.get("skillbooks",[]))+len(m.get("recipes",[]))} 筆掉落',
                value       = m['name'],
            )
            for m in monsters[:25]
        ]
        super().__init__(placeholder='找到多筆怪物，請選擇…', options=options,
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        data    = _load_drops()
        monster = data['monsters'].get(self.values[0])
        if not monster:
            await interaction.response.send_message('❌ 找不到該怪物。', ephemeral=True)
            return
        await interaction.response.send_message(embed=_monster_embed(monster), ephemeral=True)


class MonsterResultView(ui.View):
    def __init__(self, monsters: list):
        super().__init__(timeout=60)
        self.add_item(MonsterResultSelect(monsters))


class ItemResultSelect(ui.Select):
    def __init__(self, items: list, category: str, label: str):
        self.category = category
        self.label_str = label
        options = [
            discord.SelectOption(label=item[:100], value=item)
            for item in items[:25]
        ]
        super().__init__(placeholder='找到多項物品，請選擇…', options=options,
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        data    = _load_drops()
        results = _search_items(data, self.values[0], self.category)
        # 用完整名稱精確過濾
        exact = [r for r in results if any(self.values[0] == i for i in r['matched'])]
        await _send_item_results(interaction, self.values[0], exact or results, self.label_str)


class ItemResultView(ui.View):
    def __init__(self, items: list, category: str, label: str):
        super().__init__(timeout=60)
        self.add_item(ItemResultSelect(items, category, label))


# ── 怪物 Embed ────────────────────────────────────────────────────

def _monster_embed(monster: dict) -> discord.Embed:
    embed = discord.Embed(
        title = f'🐉 {monster["name"]}（Lv.{monster["level"]}）',
        color = 0xE74C3C,
    )
    drops      = monster.get('drops', [])
    skillbooks = monster.get('skillbooks', [])
    recipes    = monster.get('recipes', [])

    if drops:
        embed.add_field(name='💎 一般掉落物', value='、'.join(drops)[:1024], inline=False)
    if skillbooks:
        embed.add_field(name='📖 技能書',     value='、'.join(skillbooks)[:1024], inline=False)
    if recipes:
        embed.add_field(name='🔧 製作配方',   value='、'.join(recipes)[:1024], inline=False)
    if not drops and not skillbooks and not recipes:
        embed.description = '此怪物尚無掉落資料。'

    total = len(drops) + len(skillbooks) + len(recipes)
    embed.set_footer(text=f'共 {total} 筆掉落資料')
    return embed


async def _send_item_results(
    interaction: discord.Interaction,
    keyword: str,
    results: list,
    category_label: str,
):
    if not results:
        await interaction.response.send_message(
            f'❌ 找不到包含「{keyword}」的{category_label}掉落資料。', ephemeral=True)
        return

    embed = discord.Embed(
        title       = f'{category_label}查詢：「{keyword}」',
        description = f'共找到 **{len(results)}** 隻怪物會掉落',
        color       = 0x3498DB,
    )
    for r in results[:15]:
        m = r['monster']
        embed.add_field(
            name   = f'🐉 {m["name"]}（Lv.{m["level"]}）',
            value  = '、'.join(r['matched'])[:256],
            inline = False,
        )
    if len(results) > 15:
        embed.set_footer(text='僅顯示前 15 筆，請縮小搜尋關鍵字')
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _handle_item_query(
    interaction: discord.Interaction,
    keyword: str,
    category: str,
    label: str,
):
    data    = _load_drops()
    results = _search_items(data, keyword, category)

    if not results:
        await interaction.response.send_message(
            f'❌ 找不到包含「{keyword}」的{label}掉落資料。', ephemeral=True)
        return

    unique = _unique_items(results)

    if len(unique) == 1:
        # 只有一個符合的物品 → 直接顯示結果
        exact = [r for r in results if any(unique[0] == i for i in r['matched'])]
        await _send_item_results(interaction, unique[0], exact, label)
        return

    # 多個符合的物品 → 下拉選單讓玩家精確選擇
    embed = discord.Embed(
        title       = f'{label}搜尋「{keyword}」— 找到 {len(unique)} 個相關物品',
        description = '請從下方選單選擇要查詢的確切物品：',
        color       = 0x3498DB,
    )
    await interaction.response.send_message(
        embed=embed, view=ItemResultView(unique, category, label), ephemeral=True)


# ── 錄入表單 ──────────────────────────────────────────────────────

class DropEntryModal(ui.Modal, title='📥 掉落物錄入'):
    monster_name = ui.TextInput(
        label       = '怪物名稱',
        placeholder = '例如：緞帶肥肥',
        required    = True, max_length=50,
    )
    level = ui.TextInput(
        label       = '怪物等級',
        placeholder = '例如：120',
        required    = True, max_length=10,
    )
    drops = ui.TextInput(
        label       = '一般掉落物（用、分隔，選填）',
        style       = discord.TextStyle.paragraph,
        placeholder = '例如：火焰之心、紅色水晶、金幣袋',
        required    = False, max_length=500,
    )
    skillbooks = ui.TextInput(
        label       = '技能書（用、分隔，選填）',
        placeholder = '例如：一刀兩斷Lv.20、三飛閃Lv.30',
        required    = False, max_length=300,
    )
    recipes = ui.TextInput(
        label       = '製作配方（用、分隔，選填）',
        placeholder = '例如： 金之心製作配方、黑天使祝福製作配方',
        required    = False, max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_drops      = _parse_items(self.drops.value)
        new_skillbooks = _parse_items(self.skillbooks.value)
        new_recipes    = _parse_items(self.recipes.value)

        if not new_drops and not new_skillbooks and not new_recipes:
            await interaction.response.send_message(
                '❌ 請至少填寫一項掉落物（一般掉落物、技能書或製作配方）。', ephemeral=True)
            return

        data = _load_drops()
        key  = self.monster_name.value.strip()

        if key in data['monsters']:
            m  = data['monsters'][key]
            ex_drops = set(m.get('drops', []))
            ex_sb    = set(m.get('skillbooks', []))
            ex_rec   = set(m.get('recipes', []))

            added_d  = [i for i in new_drops      if i not in ex_drops]
            added_sb = [i for i in new_skillbooks  if i not in ex_sb]
            added_r  = [i for i in new_recipes     if i not in ex_rec]

            m['level']      = self.level.value
            m['drops']      = sorted(ex_drops | set(new_drops))
            m['skillbooks'] = sorted(ex_sb    | set(new_skillbooks))
            m['recipes']    = sorted(ex_rec   | set(new_recipes))
            is_new = False
            summary = []
            if added_d:  summary.append(f'💎 新增 {len(added_d)} 項一般掉落物')
            if added_sb: summary.append(f'📖 新增 {len(added_sb)} 本技能書')
            if added_r:  summary.append(f'🔧 新增 {len(added_r)} 項製作配方')
        else:
            data['monsters'][key] = {
                'name':       key,
                'level':      self.level.value,
                'drops':      sorted(new_drops),
                'skillbooks': sorted(new_skillbooks),
                'recipes':    sorted(new_recipes),
            }
            is_new  = True
            summary = []
            if new_drops:      summary.append(f'💎 {len(new_drops)} 項一般掉落物')
            if new_skillbooks: summary.append(f'📖 {len(new_skillbooks)} 本技能書')
            if new_recipes:    summary.append(f'🔧 {len(new_recipes)} 項製作配方')

        _save_drops(data)
        action = '新增' if is_new else '更新'
        lines  = [f'✅ 已{action}怪物「**{key}**」（Lv.{self.level.value}）\n']
        lines  += summary
        await interaction.response.send_message('\n'.join(lines), ephemeral=True)


# ── 查詢 Modal ────────────────────────────────────────────────────

class MonsterQueryModal(ui.Modal, title='🐉 怪物掉落查詢'):
    name = ui.TextInput(
        label       = '怪物名稱',
        placeholder = '例如：緞帶肥肥（支援部分名稱搜尋）',
        required    = True, max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data    = _load_drops()
        results = _search_monsters(data, self.name.value)

        if not results:
            await interaction.response.send_message(
                f'❌ 找不到名稱包含「{self.name.value}」的怪物。', ephemeral=True)
            return

        if len(results) == 1:
            await interaction.response.send_message(
                embed=_monster_embed(results[0]), ephemeral=True)
            return

        # 多筆結果 → 下拉選單讓玩家精確選擇
        embed = discord.Embed(
            title       = f'🐉 搜尋「{self.name.value}」— 共 {len(results)} 筆結果',
            description = '請從下方選單選擇要查看的怪物：',
            color       = 0xE74C3C,
        )
        await interaction.response.send_message(
            embed=embed, view=MonsterResultView(results), ephemeral=True)


class ItemDropQueryModal(ui.Modal, title='💎 掉落物查詢'):
    item = ui.TextInput(
        label       = '物品名稱',
        placeholder = '例如：紅緞帶（支援部分名稱搜尋）',
        required    = True, max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _handle_item_query(interaction, self.item.value, 'drops', '💎 掉落物')


class SkillBookQueryModal(ui.Modal, title='📖 技能書查詢'):
    item = ui.TextInput(
        label       = '技能書名稱',
        placeholder = '例如：三飛閃（支援部分名稱搜尋）',
        required    = True, max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _handle_item_query(interaction, self.item.value, 'skillbooks', '📖 技能書')


class RecipeQueryModal(ui.Modal, title='🔧 製作配方查詢'):
    item = ui.TextInput(
        label       = '配方名稱',
        placeholder = '例如：金之心（支援部分名稱搜尋）',
        required    = True, max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _handle_item_query(interaction, self.item.value, 'recipes', '🔧 製作配方')


# ── 主控面板（持久化）────────────────────────────────────────────

class DropPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='📥 掉落物錄入', style=discord.ButtonStyle.danger,
               custom_id='drop_entry_btn', row=0)
    async def entry_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.client.db.is_admin(interaction.guild_id, interaction.user):
            await interaction.response.send_message('❌ 只有管理員可以錄入掉落資料。', ephemeral=True)
            return
        await interaction.response.send_modal(DropEntryModal())

    @ui.button(label='🐉 怪物掉落查詢', style=discord.ButtonStyle.primary,
               custom_id='drop_monster_btn', row=0)
    async def monster_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MonsterQueryModal())

    @ui.button(label='💎 掉落物查詢', style=discord.ButtonStyle.secondary,
               custom_id='drop_item_btn', row=0)
    async def item_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ItemDropQueryModal())

    @ui.button(label='📖 技能書查詢', style=discord.ButtonStyle.secondary,
               custom_id='drop_skill_btn', row=1)
    async def skill_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SkillBookQueryModal())

    @ui.button(label='🔧 製作配方查詢', style=discord.ButtonStyle.secondary,
               custom_id='drop_recipe_btn', row=1)
    async def recipe_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RecipeQueryModal())


# ── Cog ──────────────────────────────────────────────────────────

class DropsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(DropPanelView())

    @app_commands.command(name='掉落物面板', description='發布掉落物查詢面板（僅限管理員）')
    @admin_only()
    async def drops_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = '🎮 掉落物資料庫',
            description = (
                '查詢怪物掉落物、技能書、製作配方！\n\n'
                '**📥 掉落物錄入** — 管理員錄入怪物掉落資料（支援累加）\n'
                '**🐉 怪物掉落查詢** — 輸入怪物名稱，查看所有掉落物\n'
                '**💎 掉落物查詢** — 輸入物品名稱，查哪些怪物會掉落\n'
                '**📖 技能書查詢** — 輸入技能書名稱，查掉落來源\n'
                '**🔧 製作配方查詢** — 輸入配方名稱，查掉落來源\n\n'
                '*所有查詢皆支援部分名稱搜尋*'
            ),
            color = 0x9B59B6,
        )
        await interaction.response.send_message(embed=embed, view=DropPanelView())

    @app_commands.command(name='刪除怪物資料', description='從資料庫刪除指定怪物的所有掉落資料（僅限管理員）')
    @app_commands.describe(怪物名稱='要刪除的怪物完整名稱')
    @admin_only()
    async def delete_monster(self, interaction: discord.Interaction, 怪物名稱: str):
        data = _load_drops()
        key  = 怪物名稱.strip()
        if key not in data['monsters']:
            await interaction.response.send_message(
                f'❌ 找不到怪物「{key}」，請確認名稱正確。', ephemeral=True)
            return
        del data['monsters'][key]
        _save_drops(data)
        await interaction.response.send_message(
            f'✅ 已刪除怪物「**{key}**」的所有掉落資料。', ephemeral=True)

    @app_commands.command(name='批量匯入掉落', description='上傳 .txt 文字檔批量匯入怪物掉落資料（僅限管理員）')
    @app_commands.describe(檔案='格式：LV.X怪物名稱 開頭，之後每行一個掉落物')
    @admin_only()
    async def bulk_import(self, interaction: discord.Interaction, 檔案: discord.Attachment):
        if not 檔案.filename.lower().endswith('.txt'):
            await interaction.response.send_message('❌ 請上傳 .txt 格式的文字檔！', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        raw_bytes = await 檔案.read()

        # 自動偵測編碼（支援 UTF-8、Big5、GBK 等）
        text = None
        used_enc = ''
        for enc in ('utf-8-sig', 'utf-8', 'big5', 'cp950', 'gbk', 'latin-1'):
            try:
                text = raw_bytes.decode(enc)
                used_enc = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if text is None:
            await interaction.followup.send(
                '❌ 無法識別檔案編碼，請將檔案另存為 **UTF-8** 格式後再試。', ephemeral=True)
            return

        monsters = _parse_drop_file(text)
        if not monsters:
            await interaction.followup.send(
                '❌ 未找到任何怪物資料。\n'
                '請確認格式：每個怪物以 `LV.X怪物名稱` 開頭，之後每行一個掉落物。',
                ephemeral=True)
            return

        data   = _load_drops()
        added  = 0
        updated = 0
        skipped_names = []

        for name, monster in monsters.items():
            if not name.strip():
                continue
            if name in data['monsters']:
                ex = data['monsters'][name]
                old_d = set(ex.get('drops', []))
                new_d = set(monster['drops'])
                ex['drops'] = sorted(old_d | new_d)
                ex['level'] = monster['level']
                updated += 1
            else:
                data['monsters'][name] = monster
                added += 1

        _save_drops(data)

        embed = discord.Embed(title='✅ 批量匯入完成', color=0x57F287)
        embed.add_field(name='➕ 新增怪物', value=f'**{added}** 隻',  inline=True)
        embed.add_field(name='🔄 更新怪物', value=f'**{updated}** 隻', inline=True)
        embed.add_field(name='📊 資料庫總計', value=f'**{len(data["monsters"])}** 隻', inline=True)
        embed.set_footer(text=f'編碼：{used_enc} ｜ 來源：{檔案.filename}')
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DropsCog(bot))
