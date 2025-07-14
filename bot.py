# bot.py – Grow a Garden Tracker (global slash commands)
# ---------------------------------------------------------------------------
"""
Fungsi utama:
1. Melacak stok & event cuaca GAG, mengirim embed otomatis ke CHANNEL_ID.
2. Menyediakan slash‑command global `/stock` & `/weather`.
3. Perintah `!sync` → paksa sync global.
"""

# ── Imports ────────────────────────────────────────────────────────────────
import os, logging, aiohttp, discord
from discord.ext import commands, tasks
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone

# ── Konfigurasi ─────────────────────────────────────────────────────────────
TOKEN        = os.getenv("TOKEN")                                 # Token bot
CHANNEL_ID   = 1393911452334555146                                # Channel tujuan
API_BASE     = "https://grow-a-garden-api-production-ec78.up.railway.app"
WEATHER_PATH = "/api/GetWeather"                                 # Endpoint event/weather
CHECK_EVERY  = 1                                                 # Interval polling (detik)
LOG_LEVEL    = "INFO"

logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                    format="[%(asctime)s] %(levelname)s: %(message)s")

# ── Discord setup ───────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True  # diperlukan utk command prefix
bot = commands.Bot(command_prefix="!", intents=intents)

# ── Cache ───────────────────────────────────────────────────────────────────
_last_timers: Dict[str, int] | None = None   # cache restock timer
_last_active_events: List[str] = []          # cache event aktif

# ── Pemetaan ikon & emoji ───────────────────────────────────────────────────
WATCHED_ITEMS = ["Sugar Apple", "Master Sprinkler", "Beanstalk", "Ember Lily", "Bug Egg"]
WATCHED_PING   = "@everyone"  # bisa ganti jadi user ID atau @everyone/@here

CATEGORY_ICON = {
    "seedsStock":  "Seeds",
    "gearStock":   "Gear",
    "eggStock":    "Eggs",
    "honeyStock":  "🍯 Honey",
    "nightStock":  "🌙 Night",
    "easterStock": "🐇 Easter",
}
CATEGORIES_ORDER = list(CATEGORY_ICON.keys())

EMOJI_MAP = {
    "Carrot": "<:carrotGag:1394286644437319691>",
    "Strawberry": "<:strawberryGag:1394292092867711018>",
    "Tomato": "<:tomatoGag:1394292648923369574>",
    "Blueberry": "<:blueberryGag:1394287893148729456>",
    "Watering Can": "<:wateringCan:1394292900053123193>",
    "Trowel": "<:trowel:1394292753118003273>",
    "Recall Wrench": "<:recallWrench:1394291908758605864>",
    "Cleaning Spray": "<:cleaningSpray:1394288446834737213>",
    "Favorite Tool": "<:favTool:1394289270369419475>",
    "Harvest Tool": "<:harvestTool:1394289905131061322>",
    "Watermellon": "<:watermellonGag:1394293019418558575>",
    "Pumpkin": "<:pumpkinGag:1394291620853186581>",
    "Orange Tulip": "<:orangeTulipGag:1394291333941694496>",
    "Bamboo": "<:bambooGag:1394287325357539338>",
    "Apple": "<:appleGag:1394287325357539338>",
    "Daffodil": "<:daffodilGag:1394288916445659227>",
    "Corn": ":corn:",
    
    "Basic Sprinkler": "<:basicSprink:1394287072528826479>",
    "Advanced Sprinkler": "<:advSprink:1394286854538526893>",
    "Godly Sprinkler": "<:godlySprink:1394289629682995261>",
    "Master Sprinkler": "<:masterSprink:1394290802074718311>",
    "Magnifying Glass": "<:magnifyingGlass:1394290418434310266>",
    
    "Common Egg": "<:commonEgg:1394288712313213039>",
    "Common Summer Egg": "<:commonSummerEgg:1394288818953256971>",
    "Paradise Egg": "<:paradiseEgg:1394291488019583048>"
}

EVENT_EMOJI = {
    "rain": "🌧️", "thunderstorm": "⛈️", "bloodnight": "🩸", "meteorshower": "☄️",
    "disco": "🕺", "jandelstorm": "🌪️", "night": "🌙", "volcano": "🌋",
    "chocolaterain": "🍫", "blackhole": "🕳️", "frost": "❄️", "bloodmoonevent": "🔴",
    "gale": "🌬️", "megaharvest": "🍌", "sungod": "𓂀", "nightevent": "🌑",
    "tropicalrain": "🌴", "auroraborealis": "🌌", "windy": "💨", "tornado": "🌪️",
    "summerharvest": "⛱️", "heatwave": "♨️",
}

# ── Helper HTTP ─────────────────────────────────────────────────────────────
async def _get_json(path: str) -> Dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as r:
            r.raise_for_status()
            return await r.json()

afetch_stock   = lambda: _get_json("/api/stock/GetStock")
fetch_weather  = lambda: _get_json(WEATHER_PATH)
_fetch_timers  = lambda: _get_json("/api/stock/restock-time")

# ── Restock / Event detection ───────────────────────────────────────────────
def _restocked(cur: Dict[str, int] | None) -> bool:
    global _last_timers
    if cur is None:
        return False
    if _last_timers is None:
        _last_timers = cur
        return False
    changed = any(v > _last_timers.get(k, 0) for k, v in cur.items())
    _last_timers = cur
    return changed

def _active_events(events_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in events_json.get("events", []) if e.get("isActive")]

def _events_changed(current: List[Dict[str, Any]]) -> bool:
    global _last_active_events
    names = [e["name"] for e in current]
    if names != _last_active_events:
        _last_active_events = names
        return True
    return False

# ── Embed builders ──────────────────────────────────────────────────────────
def _stock_embed(data: Dict[str, Any], restock: Dict[str, Any]) -> discord.Embed:
    wib_now = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
    em = discord.Embed(title=f"Grow a Garden Stock - {wib_now}", colour=0xffc107)
    em.set_footer(text="WRAITH • Stok Terbaru")
    em.timestamp = datetime.now(timezone.utc)
    
    for key in CATEGORIES_ORDER:
        items: List[Dict[str, Any]] = data.get(key, [])
        if not items:
            continue
        label = CATEGORY_ICON[key]
        cd = restock.get(key.lower().replace("stock", ""), {}).get("countdown")
        if cd:
            label += f" ({cd})"
        lines = [
            f"{item.get('emoji') or EMOJI_MAP.get(item.get('name', ''), '')} {item.get('name', '?')}: **x{item.get('value', '?')}**"
            for item in items
        ]
        em.add_field(name=label, value="\n".join(lines[:25])+"\n", inline=False)
    return em

def _weather_embed(active: List[Dict[str, Any]]) -> discord.Embed:
    wib_now = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
    em = discord.Embed(title=f"🌤️ Event Aktif – {wib_now}", colour=0xffc107)
    if not active:
        em.description = "_Tidak ada event/cuaca aktif saat ini._"
        return em
    lines = [f"{ev.get('emoji') or EVENT_EMOJI.get(ev['name'],'')} **{ev['displayName']}** – `{ev.get('timeRemaining','?')}`" for ev in active]
    em.description = "\n".join(lines)
    em.set_footer(text="WRAITH • Cuaca")
    em.timestamp = datetime.now(timezone.utc)
    return em

# ── Polling loop ────────────────────────────────────────────────────────────
@tasks.loop(seconds=CHECK_EVERY)
async def poll_api():
    try:
        stock   = await afetch_stock()
        timers  = await _fetch_timers()
        weather = await fetch_weather()
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return

    ch = bot.get_channel(CHANNEL_ID)
    if ch is None:
        logging.warning("Channel ID salah atau bot tak ada akses.")
        return

    if _restocked(stock.get("restockTimers")):
        embed = _stock_embed(stock, timers)

        # Cek apakah ada item penting
        found = []
        for items in stock.values():
            if isinstance(items, list):
                for item in items:
                    name = item.get("name", "")
                    if name in WATCHED_ITEMS:
                        found.append(name)

        content = None
        if found:
            content = f"{WATCHED_PING} ‼️ Item muncul: {', '.join(found)}"

        await ch.send(content=content, embed=embed)
        logging.info("Embed stock dikirim (restock)")
        logging.info(f"Ping dikirim untuk: {found}")

    active_now = _active_events(weather)
    if _events_changed(active_now) and active_now:
        await ch.send(embed=_weather_embed(active_now))
        logging.info("Embed weather dikirim (event aktif)")

# ── Slash commands (global) ─────────────────────────────────────────────────
@bot.tree.command(name="stock", description="Menampilkan stok Grow a Garden")
async def stock_slash(inter: discord.Interaction):
    await inter.response.defer()
    try:
        stock  = await afetch_stock()
        timers = await _fetch_timers()
        await inter.followup.send(embed=_stock_embed(stock, timers))
    except Exception as e:
        logging.error(e)
        await inter.followup.send("Gagal fetch stock.")

@bot.tree.command(name="weather", description="Tampilkan event/cuaca aktif saat ini")
async def weather_slash(inter: discord.Interaction):
    await inter.response.defer()
    try:
        weather = await fetch_weather()
        active  = _active_events(weather)
        await inter.followup.send(embed=_weather_embed(active))
    except Exception as e:
        logging.error(e)
        await inter.followup.send("Gagal fetch weather.")

@bot.command()
async def sync(ctx: commands.Context):
    synced = await bot.tree.sync()
    await ctx.send(f"✅ Synced {len(synced)} global command(s): {[c.name for c in synced]}")

# ── Event on_ready ──────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Synced {len(synced)} global command(s): {[c.name for c in synced]}")
    except Exception as e:
        logging.error(f"❌ Gagal sync slash command: {e}")

    logging.info(f"Bot online sebagai {bot.user} (ID {bot.user.id})")
    if not poll_api.is_running():
        poll_api.start()

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Isi TOKEN dan CHANNEL_ID dulu.")

    print("🔍 Slash Commands Terdaftar:")
    for cmd in bot.tree.get_commands():
        print(f" - /{cmd.name}")

    logging.info("Bot starting...")
    bot.run(TOKEN)
