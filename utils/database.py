import json
import os
from datetime import datetime, date
import pytz

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

def _path(filename):
    return os.path.join(DATA_DIR, filename)

def _load(filename, default=None):
    p = _path(filename)
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default if default is not None else {}

def _save(filename, data):
    with open(_path(filename), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Database:
    """
    資料結構說明：
    
    checkins.json — 每位使用者的簽到紀錄
    {
      "guild_id": {
        "user_id": {
          "display_name": "顯示名稱",
          "total": 123,           # 總簽到次數
          "streak": 5,            # 目前連續簽到天數
          "max_streak": 10,       # 最高連續簽到天數
          "miss": 3,              # 未簽到次數
          "miss_streak": 2,       # 目前連續未簽到天數
          "max_miss_streak": 4,   # 最高連續未簽到天數
          "last_checkin": "2024-01-01",   # 最後簽到日期
          "last_miss": "2024-01-02",      # 最後未簽到日期
          "history": ["2024-01-01", ...]  # 所有簽到日期
        }
      }
    }
    
    channel_settings.json — 每個頻道的設定
    {
      "guild_id": {
        "channel_id": {
          "reset_hour": 0,          # 簽到重置小時（0~23）
          "require_proof": false,   # 是否需要附截圖
          "min_words": 0            # 最少字數要求
        }
      }
    }
    
    guild_settings.json — 伺服器層級設定
    {
      "guild_id": {
        "timezone": "Asia/Taipei",  # 伺服器時區
        "bot_admins": ["user_id"]   # 機器人管理員清單
      }
    }
    
    nicknames.json — 使用者自訂顯示名稱
    {
      "guild_id": {
        "user_id": "真實名稱"
      }
    }
    
    blacklist.json — 黑名單
    {
      "guild_id": {
        "channel_id": ["user_id", ...]
      }
    }
    
    today_checkins.json — 今日簽到紀錄（用於 c.t 指令）
    {
      "guild_id": {
        "channel_id": {
          "date": "2024-01-01",
          "users": ["user_id", ...]
        }
      }
    }
    """

    # ─── 簽到資料 ───────────────────────────────────────────
    def get_all_checkins(self, guild_id):
        data = _load('checkins.json')
        return data.get(str(guild_id), {})

    def get_user_checkin(self, guild_id, user_id):
        data = _load('checkins.json')
        return data.get(str(guild_id), {}).get(str(user_id))

    def save_user_checkin(self, guild_id, user_id, user_data):
        data = _load('checkins.json')
        gid = str(guild_id)
        uid = str(user_id)
        if gid not in data:
            data[gid] = {}
        data[gid][uid] = user_data
        _save('checkins.json', data)

    def init_user(self, guild_id, user_id, display_name):
        existing = self.get_user_checkin(guild_id, user_id)
        if existing:
            return existing
        user_data = {
            'display_name': display_name,
            'total': 0,
            'streak': 0,
            'max_streak': 0,
            'miss': 0,
            'miss_streak': 0,
            'max_miss_streak': 0,
            'last_checkin': None,
            'last_miss': None,
            'history': []
        }
        self.save_user_checkin(guild_id, user_id, user_data)
        return user_data

    def adjust_total(self, guild_id, user_id, delta):
        user = self.get_user_checkin(guild_id, user_id)
        if not user:
            return False
        user['total'] = max(0, user['total'] + delta)
        self.save_user_checkin(guild_id, user_id, user)
        return True

    def adjust_miss(self, guild_id, user_id, delta):
        user = self.get_user_checkin(guild_id, user_id)
        if not user:
            return False
        user['miss'] = max(0, user['miss'] + delta)
        self.save_user_checkin(guild_id, user_id, user)
        return True

    def reset_leaderboard(self, guild_id, board_type):
        """重置排行榜，board_type: 'wl' 或 'll'"""
        data = _load('checkins.json')
        gid = str(guild_id)
        if gid not in data:
            return
        for uid in data[gid]:
            if board_type == 'wl':
                data[gid][uid]['total'] = 0
                data[gid][uid]['streak'] = 0
                data[gid][uid]['max_streak'] = 0
                data[gid][uid]['history'] = []
                data[gid][uid]['last_checkin'] = None
            elif board_type == 'll':
                data[gid][uid]['miss'] = 0
                data[gid][uid]['miss_streak'] = 0
                data[gid][uid]['max_miss_streak'] = 0
                data[gid][uid]['last_miss'] = None
        _save('checkins.json', data)

    # ─── 今日簽到 ────────────────────────────────────────────
    def get_today_checkins(self, guild_id, channel_id, today_str):
        data = _load('today_checkins.json')
        entry = data.get(str(guild_id), {}).get(str(channel_id), {})
        if entry.get('date') != today_str:
            return []
        return entry.get('users', [])

    def add_today_checkin(self, guild_id, channel_id, user_id, today_str):
        data = _load('today_checkins.json')
        gid, cid, uid = str(guild_id), str(channel_id), str(user_id)
        if gid not in data:
            data[gid] = {}
        if cid not in data[gid] or data[gid][cid].get('date') != today_str:
            data[gid][cid] = {'date': today_str, 'users': []}
        if uid not in data[gid][cid]['users']:
            data[gid][cid]['users'].append(uid)
        _save('today_checkins.json', data)

    # ─── 遷移：修正舊版錯誤預設值 ───────────────────────────────
    def migrate_reset_times(self):
        """將所有頻道中舊的 reset_hour=23, reset_minute=59 遷移為 0:00。"""
        data = _load('channel_settings.json')
        changed = False
        for gid, channels in data.items():
            for cid, settings in channels.items():
                if settings.get('reset_hour') == 23 and settings.get('reset_minute', 59) == 59:
                    settings['reset_hour'] = 0
                    settings['reset_minute'] = 0
                    changed = True
                    print(f'[遷移] 已將 guild={gid} channel={cid} 的重置時間從 23:59 更新為 00:00')
        if changed:
            _save('channel_settings.json', data)

    # ─── 頻道設定 ────────────────────────────────────────────
    def get_channel_settings(self, guild_id, channel_id):
        data = _load('channel_settings.json')
        defaults = {
            'reset_hour': 0,
            'reset_minute': 0,
            'require_proof': False,
            'min_words': 0
        }
        saved = data.get(str(guild_id), {}).get(str(channel_id), {})
        return {**defaults, **saved}

    def save_channel_settings(self, guild_id, channel_id, settings):
        data = _load('channel_settings.json')
        gid, cid = str(guild_id), str(channel_id)
        if gid not in data:
            data[gid] = {}
        data[gid][cid] = settings
        _save('channel_settings.json', data)

    # ─── 伺服器設定 ──────────────────────────────────────────
    def get_guild_settings(self, guild_id):
        data = _load('guild_settings.json')
        return data.get(str(guild_id), {
            'timezone': 'Asia/Taipei',
            'bot_admins': []
        })

    def save_guild_settings(self, guild_id, settings):
        data = _load('guild_settings.json')
        data[str(guild_id)] = settings
        _save('guild_settings.json', data)


    def get_checkin_channels(self, guild_id):
        """取得此伺服器設定的簽到頻道清單，空清單代表不限制"""
        gs = self.get_guild_settings(guild_id)
        return gs.get('checkin_channels', [])

    def add_checkin_channel(self, guild_id, channel_id):
        gs = self.get_guild_settings(guild_id)
        if 'checkin_channels' not in gs:
            gs['checkin_channels'] = []
        cid = str(channel_id)
        if cid not in gs['checkin_channels']:
            gs['checkin_channels'].append(cid)
        self.save_guild_settings(guild_id, gs)

    def remove_checkin_channel(self, guild_id, channel_id):
        gs = self.get_guild_settings(guild_id)
        cid = str(channel_id)
        if cid in gs.get('checkin_channels', []):
            gs['checkin_channels'].remove(cid)
            self.save_guild_settings(guild_id, gs)
            return True
        return False

    def is_checkin_channel(self, guild_id, channel_id):
        """檢查是否為允許簽到的頻道，清單為空代表全部頻道都允許"""
        channels = self.get_checkin_channels(guild_id)
        if not channels:
            return True
        return str(channel_id) in channels

    def get_timezone(self, guild_id):
        gs = self.get_guild_settings(guild_id)
        return gs.get('timezone', 'Asia/Taipei')

    def get_now(self, guild_id):
        tz = pytz.timezone(self.get_timezone(guild_id))
        return datetime.now(tz)

    def get_today_str(self, guild_id, reset_hour=0, reset_minute=0):
        """
        以 reset_hour:reset_minute 為每日分界線。
        預設 00:00（午夜），即每天午夜之後算隔天。
        若 reset_hour=4，則凌晨 0~3 點簽到仍算前一天。
        """
        now = self.get_now(guild_id)
        now_minutes = now.hour * 60 + now.minute
        reset_minutes = reset_hour * 60 + reset_minute
        if now_minutes < reset_minutes:
            from datetime import timedelta
            now = now - timedelta(days=1)
        return now.strftime('%Y-%m-%d')

    # ─── 暱稱 ────────────────────────────────────────────────
    def get_nickname(self, guild_id, user_id):
        data = _load('nicknames.json')
        return data.get(str(guild_id), {}).get(str(user_id))

    def set_nickname(self, guild_id, user_id, name):
        data = _load('nicknames.json')
        gid, uid = str(guild_id), str(user_id)
        if gid not in data:
            data[gid] = {}
        data[gid][uid] = name
        _save('nicknames.json', data)
        # 同步更新 checkins.json 裡的 display_name
        user = self.get_user_checkin(guild_id, user_id)
        if user:
            user['display_name'] = name
            self.save_user_checkin(guild_id, user_id, user)

    def get_display_name(self, guild_id, user_id, fallback='未知'):
        nn = self.get_nickname(guild_id, user_id)
        if nn:
            return nn
        user = self.get_user_checkin(guild_id, user_id)
        if user:
            return user.get('display_name', fallback)
        return fallback

    # ─── 黑名單 ──────────────────────────────────────────────
    def get_blacklist(self, guild_id, channel_id):
        data = _load('blacklist.json')
        return data.get(str(guild_id), {}).get(str(channel_id), [])

    def is_blacklisted(self, guild_id, channel_id, user_id):
        bl = self.get_blacklist(guild_id, channel_id)
        return str(user_id) in bl

    def add_to_blacklist(self, guild_id, channel_id, user_id):
        data = _load('blacklist.json')
        gid, cid, uid = str(guild_id), str(channel_id), str(user_id)
        if gid not in data:
            data[gid] = {}
        if cid not in data[gid]:
            data[gid][cid] = []
        if uid not in data[gid][cid]:
            data[gid][cid].append(uid)
        _save('blacklist.json', data)

    def remove_from_blacklist(self, guild_id, channel_id, user_id):
        data = _load('blacklist.json')
        gid, cid, uid = str(guild_id), str(channel_id), str(user_id)
        if gid in data and cid in data[gid] and uid in data[gid][cid]:
            data[gid][cid].remove(uid)
            _save('blacklist.json', data)
            return True
        return False

    # ─── 管理員 ──────────────────────────────────────────────
    def is_bot_admin(self, guild_id, user_id):
        gs = self.get_guild_settings(guild_id)
        return str(user_id) in gs.get('bot_admins', [])

    def add_bot_admin(self, guild_id, user_id):
        gs = self.get_guild_settings(guild_id)
        if 'bot_admins' not in gs:
            gs['bot_admins'] = []
        uid = str(user_id)
        if uid not in gs['bot_admins']:
            gs['bot_admins'].append(uid)
        self.save_guild_settings(guild_id, gs)

    def remove_bot_admin(self, guild_id, user_id):
        gs = self.get_guild_settings(guild_id)
        uid = str(user_id)
        if uid in gs.get('bot_admins', []):
            gs['bot_admins'].remove(uid)
            self.save_guild_settings(guild_id, gs)
            return True
        return False

    def is_admin(self, guild_id, member):
        """檢查是否為伺服器管理員或機器人管理員"""
        if member.guild_permissions.administrator:
            return True
        return self.is_bot_admin(guild_id, member.id)

    # ─── 簽到幣 & 抽獎卷 ─────────────────────────────────────────
    def get_user_wallet(self, guild_id, user_id) -> dict:
        data = _load('coins.json')
        default = {'coins': 0, 'weekly_tickets': 0, 'monthly_tickets': 0}
        return data.get(str(guild_id), {}).get(str(user_id), dict(default))

    def save_user_wallet(self, guild_id, user_id, wallet: dict):
        data = _load('coins.json')
        gid, uid = str(guild_id), str(user_id)
        data.setdefault(gid, {})[uid] = wallet
        _save('coins.json', data)

    def add_coins(self, guild_id, user_id, amount: int) -> int:
        """新增簽到幣，回傳新餘額。"""
        wallet = self.get_user_wallet(guild_id, user_id)
        wallet['coins'] = max(0, wallet.get('coins', 0) + amount)
        self.save_user_wallet(guild_id, user_id, wallet)
        return wallet['coins']

    def exchange_tickets(self, guild_id, user_id, ticket_type: str, cost: int):
        """兌換抽獎卷。回傳 (是否成功, 更新後的 wallet)。"""
        wallet = self.get_user_wallet(guild_id, user_id)
        if wallet.get('coins', 0) < cost:
            return False, wallet
        wallet['coins'] -= cost
        key = f'{ticket_type}_tickets'
        wallet[key] = wallet.get(key, 0) + 1
        self.save_user_wallet(guild_id, user_id, wallet)
        return True, wallet

    def use_ticket(self, guild_id, user_id, ticket_type: str):
        """消耗一張抽獎卷。回傳 (是否成功, 更新後的 wallet)。"""
        wallet = self.get_user_wallet(guild_id, user_id)
        key = f'{ticket_type}_tickets'
        if wallet.get(key, 0) <= 0:
            return False, wallet
        wallet[key] -= 1
        self.save_user_wallet(guild_id, user_id, wallet)
        return True, wallet

    def adjust_tickets(self, guild_id, user_id, ticket_type: str, delta: int) -> int:
        """管理員增減抽獎卷，回傳新張數。"""
        wallet = self.get_user_wallet(guild_id, user_id)
        key = f'{ticket_type}_tickets'
        wallet[key] = max(0, wallet.get(key, 0) + delta)
        self.save_user_wallet(guild_id, user_id, wallet)
        return wallet[key]

    def batch_adjust_tickets(self, guild_id, user_ids: list, ticket_type: str, delta: int):
        """批量增減多位成員的抽獎卷（一次讀寫，效率高）。"""
        data = _load('coins.json')
        gid  = str(guild_id)
        key  = f'{ticket_type}_tickets'
        data.setdefault(gid, {})
        for uid in user_ids:
            s = str(uid)
            w = data[gid].get(s, {'coins': 0, 'weekly_tickets': 0, 'monthly_tickets': 0})
            w[key] = max(0, w.get(key, 0) + delta)
            data[gid][s] = w
        _save('coins.json', data)

    def batch_adjust_coins(self, guild_id, user_ids: list, delta: int):
        """批量增減多位成員的簽到幣（一次讀寫，效率高）。"""
        data = _load('coins.json')
        gid  = str(guild_id)
        data.setdefault(gid, {})
        for uid in user_ids:
            s = str(uid)
            w = data[gid].get(s, {'coins': 0, 'weekly_tickets': 0, 'monthly_tickets': 0})
            w['coins'] = max(0, w.get('coins', 0) + delta)
            data[gid][s] = w
        _save('coins.json', data)
