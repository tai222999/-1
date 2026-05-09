# 📋 Discord 簽到機器人

一個功能完整的 Discord 簽到機器人，支援多頻道、黑名單、排行榜、連續簽到等功能。

---

## 🚀 快速開始

### 1. 安裝依賴套件

```bash
pip install -r requirements.txt
```

### 2. 設定 Bot Token

編輯 `bot.py`，將以下行中的 `你的Bot Token` 替換為你的 Discord Bot Token：

```python
TOKEN = os.getenv('DISCORD_TOKEN', '你的Bot Token')
```

或設定環境變數（建議）：

```bash
# Linux / macOS
export DISCORD_TOKEN=你的Bot_Token

# Windows
set DISCORD_TOKEN=你的Bot_Token
```

### 3. 啟動機器人

```bash
python bot.py
```

---

## 📁 專案結構

```
discord-checkin-bot/
├── bot.py                        # 主程式入口
├── requirements.txt
├── utils/
│   ├── database.py               # 資料庫管理（JSON 檔案）
│   └── config.py                 # 時區設定
├── commands/
│   ├── user/
│   │   ├── manual.py             # c.m 使用說明
│   │   ├── checkin.py            # c.c 簽到
│   │   ├── today.py              # c.t 今日簽到名單
│   │   ├── leaderboards.py       # c.wl / c.ll / c.dl 排行榜
│   │   └── reset_info.py         # c.cr 重置時間資訊
│   └── admin/
│       ├── nickname.py           # c.n 暱稱管理
│       ├── adjust.py             # c.a / c.z 調整次數
│       ├── settings.py           # c.r / c.e / c.w / c.tz 設定
│       ├── blacklist.py          # c.d 黑名單管理
│       ├── admin_manage.py       # c.g 管理員管理
│       └── leaderboard_reset.py  # c.lr 排行榜重置
└── data/                         # 自動建立的資料夾
    ├── checkins.json             # 使用者簽到資料
    ├── channel_settings.json     # 頻道設定
    ├── guild_settings.json       # 伺服器設定
    ├── nicknames.json            # 使用者暱稱
    ├── blacklist.json            # 黑名單
    └── today_checkins.json       # 今日簽到快取
```

---

## 📖 指令列表

### 👤 所有人可使用

| 指令 | 說明 |
|------|------|
| `c.m` | 顯示使用說明 |
| `c.c [訊息]` | 發送簽到（每日一次） |
| `c.t` | 查看今天已簽到的人 |
| `c.wl` | 簽到排行榜（加 `streak` 顯示連續排行） |
| `c.ll` | 未簽到排行榜（加 `streak` 顯示連續排行） |
| `c.dl` | 距離上次簽到天數排行榜 |
| `c.cr` | 查看此頻道的重置時間與時區 |

### 🔧 僅限管理員

| 指令 | 說明 |
|------|------|
| `c.n @使用者 [名稱]` | 設定使用者的顯示名稱（追蹤真實姓名） |
| `c.a @使用者 [數字]` | 增減簽到次數（負數為減少） |
| `c.z @使用者 [數字]` | 增減未簽到次數（負數為減少） |
| `c.r [0~23]` | 設定此頻道每日重置時間 |
| `c.e` | 切換是否需要附截圖才能簽到 |
| `c.w [字數]` | 設定簽到訊息最少字數 |
| `c.d block @使用者` | 將使用者加入黑名單 |
| `c.d unblock @使用者` | 解除黑名單 |
| `c.d list` | 查看黑名單 |
| `c.g add @使用者` | 新增機器人管理員 |
| `c.g remove @使用者` | 移除機器人管理員 |
| `c.g list` | 查看機器人管理員清單 |
| `c.tz [時區]` | 設定伺服器時區（不填參數查看可用時區） |
| `c.lr [wl/ll]` | 重置排行榜（需二次確認） |

---

## 🔒 黑名單系統

黑名單使用者：
- **無法**在指定頻道發送簽到
- 簽到訊息會被**靜默刪除**，並以私訊通知
- **不計入**任何排行榜統計
- 管理員可隨時封鎖或解除封鎖

```
c.d block @使用者   → 封鎖
c.d unblock @使用者 → 解除封鎖
c.d list            → 查看黑名單
```

---

## 🌏 時區設定

預設時區為 `Asia/Taipei`（台灣時間）。

可用 `c.tz` 查看支援的時區清單，並用 `c.tz [時區名稱]` 設定：

```
c.tz Asia/Taipei
c.tz Asia/Tokyo
c.tz America/New_York
```

---

## ⚙️ Discord 機器人設定需求

在 [Discord Developer Portal](https://discord.com/developers/applications) 中，請確認以下設定已啟用：

**Bot → Privileged Gateway Intents：**
- ✅ `SERVER MEMBERS INTENT`
- ✅ `MESSAGE CONTENT INTENT`

**OAuth2 → URL Generator → Scopes：**
- ✅ `bot`

**Bot Permissions（建議）：**
- ✅ Read Messages/View Channels
- ✅ Send Messages
- ✅ Manage Messages（用於刪除黑名單使用者的訊息）
- ✅ Embed Links
- ✅ Read Message History

---

## 📊 資料儲存

所有資料以 JSON 格式儲存在 `data/` 資料夾中，輕量無需資料庫。
如需遷移資料，只需複製 `data/` 資料夾即可。
