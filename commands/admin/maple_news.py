import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
from bs4 import BeautifulSoup
import json
import re
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

from utils.database import _load, _save, DATA_DIR
from utils.helpers import admin_only

NEWS_URLS = [
    'https://tw.maplestar.io/news/notices',   # 公告
    'https://tw.maplestar.io/news/updates',   # 更新
]
BASE_URL    = 'https://tw.maplestar.io'
SITEMAP_URL = 'https://tw.maplestar.io/sitemap.xml'
RSS_URLS    = [
    'https://tw.maplestar.io/rss.xml',
    'https://tw.maplestar.io/feed.xml',
    'https://tw.maplestar.io/news/rss',
]

# 只發布最近幾天內的文章（避免抓到大量舊文章）
MAX_AGE_DAYS = 3

# 匹配公告/更新文章 URL（路徑最後一段必須含數字，排除 /announcements、/inspections 等分類頁）
ARTICLE_URL_RE = re.compile(r'/news/(notice[s]?|update[s]?|maintenance[s]?)/(?=[^/]*\d)[^/?#]+')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-TW,zh;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': BASE_URL,
}

LOG_FILE = 'news_log.json'


# ── 標題清理 ──────────────────────────────────────────────────────

def _clean_title(raw: str) -> str:
    """移除結尾 N 標記，並在類別前綴後加上 ｜ 分隔符。"""
    raw = raw.strip()
    raw = re.sub(r'\s*N$', '', raw).strip()
    for cat in ['公告', '維護', '更新']:
        if raw.startswith(cat) and len(raw) > len(cat):
            rest = raw[len(cat):]
            if not rest.startswith('｜') and not rest.startswith('|'):
                raw = f'{cat}｜{rest}'
            break
    return raw


# ── HTTP 工具 ─────────────────────────────────────────────────────

async def _fetch(session: aiohttp.ClientSession, url: str,
                 delay: float = 0.5) -> str | None:
    await asyncio.sleep(delay)
    try:
        async with session.get(
            url, headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True
        ) as r:
            if r.status == 200:
                return await r.text(encoding='utf-8', errors='replace')
            if r.status == 429:
                retry = int(r.headers.get('Retry-After', 60))
                print(f'[楓星新聞] 被限速 429，等待 {retry}s')
                await asyncio.sleep(retry)
            else:
                print(f'[楓星新聞] HTTP {r.status} → {url}')
    except Exception as e:
        print(f'[楓星新聞] 無法取得 {url}：{e}')
    return None


# ── 解析工具 ──────────────────────────────────────────────────────

def _next_data(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    tag  = soup.find('script', id='__NEXT_DATA__')
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception:
            pass
    return {}


def _find_articles_in_json(data) -> list[dict]:
    results = []
    seen    = set()

    def _walk(obj):
        if isinstance(obj, dict):
            url   = (obj.get('url') or obj.get('href') or obj.get('link')
                     or obj.get('path') or '')
            title = (obj.get('title') or obj.get('subject') or obj.get('name') or '')
            date  = (obj.get('createdAt') or obj.get('publishedAt')
                     or obj.get('date') or obj.get('updatedAt') or '')
            if title and url and ARTICLE_URL_RE.search(str(url)):
                url_str = str(url)
                full = url_str if url_str.startswith('http') else BASE_URL + url_str
                if full not in seen:
                    seen.add(full)
                    results.append({
                        'url':   full,
                        'title': _clean_title(str(title)),
                        'date':  str(date),
                    })
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return results


def _find_articles_in_html(html: str) -> list[dict]:
    """從 HTML <a> 標籤找出公告連結（含標題）。"""
    soup    = BeautifulSoup(html, 'html.parser')
    seen    = set()
    results = []
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if ARTICLE_URL_RE.search(href):
            full = href if href.startswith('http') else BASE_URL + href
            if full not in seen:
                seen.add(full)
                title = _clean_title(a.get_text(strip=True) or '')
                results.append({'url': full, 'title': title, 'date': ''})
    return results


def _parse_date(raw: str) -> datetime | None:
    """將各種日期字串解析成 UTC datetime，失敗回傳 None。"""
    if not raw:
        return None
    raw = raw.strip()

    # ① fromisoformat（Python 內建，支援 +00:00 格式；先把 Z 換成 +00:00）
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # ② 手動格式備用（不做截斷，直接比對）
    for fmt in [
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M%z',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%Y.%m.%d %H:%M',
    ]:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _is_recent(date_str: str) -> bool:
    """判斷日期是否在 MAX_AGE_DAYS 天內；無日期或無法解析一律排除。"""
    if not date_str:
        return False
    dt = _parse_date(date_str)
    if dt is None:
        return False
    return datetime.now(timezone.utc) - dt <= timedelta(days=MAX_AGE_DAYS)


def _find_urls_in_sitemap(xml: str) -> list[dict]:
    """從 sitemap.xml 取得公告 URL 與日期（無標題）。"""
    seen    = set()
    results = []
    for block in re.findall(r'<url>(.*?)</url>', xml, re.DOTALL):
        loc_m = re.search(r'<loc>(.*?)</loc>', block)
        if not loc_m:
            continue
        url = loc_m.group(1).strip()
        if not ARTICLE_URL_RE.search(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        lastmod = ''
        lm_m = re.search(r'<lastmod>(.*?)</lastmod>', block)
        if lm_m:
            lastmod = lm_m.group(1).strip()
        results.append({'url': url, 'title': '', 'date': lastmod})
    return results


def _extract_title_from_html(html: str, fallback: str = '') -> tuple[str, str]:
    """
    從個別文章頁面取得 (title, date)。
    依序嘗試 __NEXT_DATA__ → <title> → <h1>。
    """
    # ① __NEXT_DATA__ JSON
    data = _next_data(html)
    if data:
        props = data.get('props', {}).get('pageProps', {})
        for key in ['article', 'post', 'notice', 'data', 'item', 'detail', 'notice_detail']:
            obj = props.get(key)
            if isinstance(obj, dict):
                t = obj.get('title') or obj.get('subject') or ''
                d = (obj.get('createdAt') or obj.get('publishedAt')
                     or obj.get('date') or '')
                if t:
                    return _clean_title(str(t)), str(d)
        # 遞迴搜尋 pageProps
        arts = _find_articles_in_json(props)
        if arts:
            return arts[0]['title'], arts[0]['date']

    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()

    # ② <title> 標籤（去掉網站名稱後綴）
    title_tag = soup.find('title')
    if title_tag:
        t = title_tag.get_text(strip=True)
        t = re.sub(r'\s*[|\-–—]\s*.*楓.*$', '', t).strip()
        if t and len(t) > 2:
            return _clean_title(t), ''

    # ③ <h1>
    h1 = soup.find('h1')
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return _clean_title(t), ''

    return fallback, ''


async def _get_article_meta(session: aiohttp.ClientSession,
                            meta: dict) -> dict:
    """
    確保文章有標題。若標題為空，抓取個別頁面取得。
    """
    if meta.get('title'):
        return meta

    html = await _fetch(session, meta['url'], delay=0.8)
    if not html:
        return meta

    title, date = _extract_title_from_html(html)
    return {
        'url':   meta['url'],
        'title': title or '楓星公告',
        'date':  meta.get('date') or date,
    }


# ── 收集公告清單 ──────────────────────────────────────────────────

async def _try_json_api(session: aiohttp.ClientSession, url: str) -> list[dict]:
    text = await _fetch(session, url, delay=0.3)
    if not text:
        return []
    try:
        return _find_articles_in_json(json.loads(text))
    except Exception:
        return []


async def _discover_api_from_js(session: aiohttp.ClientSession,
                                html: str) -> list[dict]:
    """
    掃描 Next.js JS bundle，自動找出公告列表的 API 端點並呼叫。
    這是找到動態載入文章（如 5/8 新文章）的最直接方式。
    """
    soup   = BeautifulSoup(html, 'html.parser')
    chunks = [
        s['src'] for s in soup.find_all('script', src=True)
        if '_next/static' in s.get('src', '')
    ]

    discovered_apis: set[str] = set()
    for chunk_src in chunks[:8]:   # 只掃前 8 個 chunk
        url  = chunk_src if chunk_src.startswith('http') else BASE_URL + chunk_src
        text = await _fetch(session, url, delay=0.2)
        if not text:
            continue
        # 尋找含有 notice/news/post 字樣的 API 路徑
        for m in re.finditer(
            r'["\`](/api/[^"\`\s?#]{3,60})["\`]', text
        ):
            path = m.group(1)
            if any(k in path.lower() for k in ['notice', 'news', 'post', 'article']):
                discovered_apis.add(path)
        # 也找完整 URL
        for m in re.finditer(
            r'["\`](https?://[^"\`\s?#]{5,80}(?:notice|news|post|article)[^"\`\s?#]*)["\`]',
            text
        ):
            discovered_apis.add(m.group(1))

    results: list[dict] = []
    for api_path in discovered_apis:
        full_url = api_path if api_path.startswith('http') else BASE_URL + api_path
        print(f'[楓星新聞] 🔍 嘗試 JS 找到的 API：{full_url}')
        arts = await _try_json_api(session, full_url)
        if arts:
            print(f'[楓星新聞] ✅ JS API 成功！找到 {len(arts)} 篇')
            results.extend(arts)

    return results


def _find_articles_in_rss(xml: str) -> list[dict]:
    """從 RSS/Atom XML 找出公告連結。"""
    seen    = set()
    results = []
    # <item> 或 <entry>
    for block in re.findall(r'<(?:item|entry)>(.*?)</(?:item|entry)>', xml, re.DOTALL):
        link_m = (re.search(r'<link[^>]*>(.*?)</link>', block)
                  or re.search(r'<link[^>]+href=["\']([^"\']+)["\']', block))
        if not link_m:
            continue
        url = link_m.group(1).strip()
        if not ARTICLE_URL_RE.search(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        title_m = re.search(r'<title[^>]*>(.*?)</title>', block, re.DOTALL)
        title = ''
        if title_m:
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            title = _clean_title(title)
        date_m = re.search(r'<(?:pubDate|published|updated|dc:date)>(.*?)</(?:pubDate|published|updated|dc:date)>', block)
        date = date_m.group(1).strip() if date_m else ''
        results.append({'url': url, 'title': title, 'date': date})
    return results


async def _collect_all_articles(session: aiohttp.ClientSession) -> list[dict]:
    """
    從多個來源彙整文章：
    ① JS bundle 自動發現 API（動態載入的最新文章）
    ② RSS
    ③ 清單頁（Next.js data API / __NEXT_DATA__ / HTML）
    ④ Sitemap（補充）
    """
    all_arts: dict[str, dict] = {}

    def _merge(arts: list[dict]):
        for a in arts:
            url = a['url']
            if url not in all_arts:
                all_arts[url] = a
            else:
                # 用有標題/日期的版本補全
                if not all_arts[url].get('title') and a.get('title'):
                    all_arts[url]['title'] = a['title']
                if not all_arts[url].get('date') and a.get('date'):
                    all_arts[url]['date'] = a['date']

    # ── 先取第一個清單頁的 HTML（用於 JS bundle 掃描）──────────
    first_html = await _fetch(session, NEWS_URLS[0], delay=1.0)

    # ① JS bundle 自動發現 API
    if first_html:
        js_arts = await _discover_api_from_js(session, first_html)
        _merge(js_arts)

    # ② RSS
    for rss_url in RSS_URLS:
        rss_text = await _fetch(session, rss_url, delay=0.5)
        if rss_text:
            arts = _find_articles_in_rss(rss_text)
            if arts:
                print(f'[楓星新聞] RSS 找到 {len(arts)} 篇')
                _merge(arts)
                break

    # ③ 清單頁（HTML + Next.js data API）
    htmls = {NEWS_URLS[0]: first_html}
    for list_url in NEWS_URLS[1:]:
        htmls[list_url] = await _fetch(session, list_url, delay=1.0)

    for list_url, html in htmls.items():
        if not html:
            continue
        data     = _next_data(html)
        build_id = data.get('buildId', '')

        if build_id:
            path    = list_url.replace(BASE_URL, '').strip('/')
            api_url = f'{BASE_URL}/_next/data/{build_id}/{path}.json'
            api_txt = await _fetch(session, api_url, delay=0.5)
            if api_txt:
                try:
                    _merge(_find_articles_in_json(json.loads(api_txt)))
                except Exception:
                    pass

        _merge(_find_articles_in_json(data))
        _merge(_find_articles_in_html(html))

    # ④ Sitemap（補充未找到的 URL）
    sitemap_xml = await _fetch(session, SITEMAP_URL, delay=1.0)
    if sitemap_xml:
        _merge(_find_urls_in_sitemap(sitemap_xml))

    result = list(all_arts.values())
    result.sort(key=lambda x: x.get('date') or '', reverse=True)
    print(f'[楓星新聞] 共收集到 {len(result)} 篇（含所有日期）')
    return result


# ── 資料庫輔助（原子寫入）────────────────────────────────────────

def _load_log() -> tuple[set, datetime | None]:
    """讀取發布紀錄，回傳 (posted URL 集合, 最後發布文章的時間)。"""
    data     = _load(LOG_FILE)
    urls     = set(data.get('posted', []))
    raw_date = data.get('last_posted_date', '')
    last_dt  = _parse_date(raw_date) if raw_date else None
    print(f'[楓星新聞] 讀取紀錄：{len(urls)} 筆，最後發布：{raw_date or "無"}')
    return urls, last_dt


def _save_log(posted: set, last_dt: datetime | None):
    """原子寫入發布紀錄（URL 集合 + 最後發布時間）。"""
    log_path = os.path.join(DATA_DIR, LOG_FILE)
    tmp_path = log_path + '.tmp'
    payload  = {
        'posted':           list(posted),
        'last_posted_date': last_dt.isoformat() if last_dt else '',
    }
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, log_path)
    print(f'[楓星新聞] 已儲存紀錄：{len(posted)} 筆，最後：{payload["last_posted_date"]}')


# ── Embed 排版 ────────────────────────────────────────────────────

def _format_embed(meta: dict, url: str) -> discord.Embed:
    title = (meta.get('title') or '楓星公告').strip()
    date  = (meta.get('date') or '').strip()
    # 日期格式化：去掉毫秒與時區後綴，只保留 YYYY-MM-DD HH:MM
    date = re.sub(r'T(\d{2}:\d{2}).*', r' \1', date)
    embed = discord.Embed(title=f'📢 {title}', color=0xF1A120, url=url)
    footer = f'發布時間：{date} ｜ 來源：楓星官網' if date else '來源：楓星官網'
    embed.set_footer(text=footer)
    return embed


# ── Cog ─────────────────────────────────────────────────────────

class MapleNews(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.news_loop.start()

    def cog_unload(self):
        self.news_loop.cancel()

    def _news_channel(self, guild_id: int) -> int | None:
        cid = self.bot.db.get_guild_settings(guild_id).get('news_channel')
        return int(cid) if cid else None

    async def _fetch_and_post(self) -> tuple[int, int]:
        posted, last_dt = _load_log()
        new_posted = set()
        new_last_dt = last_dt

        async with aiohttp.ClientSession() as session:
            all_arts = await _collect_all_articles(session)

            # ① 只看最近 MAX_AGE_DAYS 天內的文章
            recent = [a for a in all_arts if _is_recent(a.get('date', ''))]

            # ② 只要比「上次已發布的最新文章」更新的，或 URL 不在紀錄中且沒有日期
            def _should_post(a: dict) -> bool:
                if a['url'] in posted:
                    return False                       # 已發布過
                art_dt = _parse_date(a.get('date', ''))
                if art_dt is None:
                    return False                       # 無法確認日期，一律跳過
                if last_dt is None:
                    return True                        # 從未發布過，發布所有有日期的近期文章
                return art_dt > last_dt               # 僅發布比上次更新的

            new_arts = [a for a in recent if _should_post(a)]
            print(
                f'[楓星新聞] 近 {MAX_AGE_DAYS} 天 {len(recent)} 篇，'
                f'比上次（{last_dt.strftime("%m-%d %H:%M") if last_dt else "無"}）更新：{len(new_arts)} 篇'
            )

            for meta in new_arts[:5]:
                meta  = await _get_article_meta(session, meta)
                url   = meta['url']
                embed = _format_embed(meta, url)

                for guild in self.bot.guilds:
                    ch_id = self._news_channel(guild.id)
                    if not ch_id:
                        continue
                    ch = guild.get_channel(ch_id)
                    if ch:
                        try:
                            await ch.send(embed=embed)
                            await asyncio.sleep(1)
                        except Exception as e:
                            print(f'[楓星新聞] 無法發送至 {ch_id}：{e}')

                new_posted.add(url)
                # 更新最後發布時間
                art_dt = _parse_date(meta.get('date', ''))
                if art_dt and (new_last_dt is None or art_dt > new_last_dt):
                    new_last_dt = art_dt

        if new_posted:
            _save_log(posted | new_posted, new_last_dt)
            print(f'[楓星新聞] 已發布 {len(new_posted)} 篇。')

        return len(all_arts), len(new_posted)

    @tasks.loop(minutes=10)
    async def news_loop(self):
        await self._fetch_and_post()

    @news_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(15)

    # ── /設定公告頻道 ────────────────────────────────────────────
    @app_commands.command(name='設定公告頻道', description='設定楓星公告自動發布的頻道')
    @app_commands.describe(頻道='公告將自動發布到的頻道')
    @admin_only()
    async def slash_set_news_ch(self, interaction: discord.Interaction,
                                 頻道: discord.TextChannel):
        gs = self.bot.db.get_guild_settings(interaction.guild_id)
        gs['news_channel'] = str(頻道.id)
        self.bot.db.save_guild_settings(interaction.guild_id, gs)
        await interaction.response.send_message(
            f'✅ 楓星公告將自動發布至 {頻道.mention}（每 10 分鐘檢查一次）',
            ephemeral=True
        )

    # ── /立即抓取公告 ────────────────────────────────────────────
    @app_commands.command(name='立即抓取公告', description='立即抓取楓星官網最新公告並發布')
    @admin_only()
    async def slash_fetch_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        total, posted = await self._fetch_and_post()
        msg = (f'✅ 抓取完成！共找到 {total} 篇，已發布 {posted} 篇新公告。'
               if posted else
               f'✅ 抓取完成！共找到 {total} 篇，目前沒有新公告。')
        await interaction.followup.send(msg, ephemeral=True)

    # ── /清除公告紀錄 ────────────────────────────────────────────
    @app_commands.command(name='清除公告紀錄', description='清除已發布公告的紀錄（下次抓取時將重新發布所有公告）')
    @admin_only()
    async def slash_clear_news_log(self, interaction: discord.Interaction):
        _save_log(set(), None)
        await interaction.response.send_message(
            '✅ 已清除公告發布紀錄，下次抓取時將重新發布所有公告。\n'
            '⚠️ 建議謹慎使用，避免大量舊公告同時發布。',
            ephemeral=True
        )

    # ── /診斷公告 ────────────────────────────────────────────────
    @app_commands.command(name='診斷公告', description='顯示目前爬蟲找到的公告清單（不發布）')
    @admin_only()
    async def slash_diagnose(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        posted, last_dt = _load_log()

        async with aiohttp.ClientSession() as session:
            all_arts = await _collect_all_articles(session)

        if not all_arts:
            await interaction.followup.send('❌ 找不到任何公告。', ephemeral=True)
            return

        recent   = [a for a in all_arts if _is_recent(a.get('date', ''))]
        last_str = last_dt.strftime('%m-%d %H:%M') if last_dt else '無'
        new      = [
            a for a in recent
            if a['url'] not in posted and (
                last_dt is None or
                _parse_date(a.get('date', '')) is None or
                _parse_date(a.get('date', '')) > last_dt
            )
        ]
        lines = [
            f'**近 {MAX_AGE_DAYS} 天共 {len(recent)} 篇，{len(new)} 篇待發布**',
            f'最後發布時間：`{last_str}`（只發比這更新的）\n',
        ]
        for i, a in enumerate(recent[:25], 1):
            mark  = '🆕 ' if a['url'] not in posted else '✅ '
            date  = re.sub(r'T\d{2}:\d{2}.*', '', a.get('date') or '') or '無日期'
            title = (a.get('title') or a['url'].split('/')[-1][:20])[:28]
            lines.append(f'{mark}`{i:>2}.` {date} {title}')
        await interaction.followup.send('\n'.join(lines), ephemeral=True)

    # ── /重啟機器人 ──────────────────────────────────────────────
    @app_commands.command(name='重啟機器人', description='重啟機器人並重新同步所有斜線指令')
    @admin_only()
    async def slash_restart(self, interaction: discord.Interaction):
        await interaction.response.send_message('🔄 正在重啟機器人...', ephemeral=True)
        await asyncio.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)


async def setup(bot):
    await bot.add_cog(MapleNews(bot))
