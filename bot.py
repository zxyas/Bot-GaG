# bot.py – GAG Stock + Weather Tracker
# ──────────────────────────────────────────────────────────────────────────────
import logging, os, aiohttp, discord
from discord.ext import commands, tasks
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone

# ─── KONFIG ───────────────────────────────────────────────────────────────────
TOKEN       = os.getenv("TOKEN")                               # token bot
GUILD_ID    = 1221173165179277425                              # ID server
CHANNEL_ID  = 1393911452334555146                              # ID channel tujuan
API_BASE    = "https://grow-a-garden-api-production-ec78.up.railway.app"
CHECK_EVERY = 10                                               # detik polling
LOG_LEVEL   = "INFO"
WEATHER_PATH = "/api/GetWeather"                            # <- ubah kalau beda

logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                    format="[%(asctime)s] %(levelname)s: %(message)s")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)


# ─── CACHE ────────────────────────────────────────────────────────────────────
_last_timers: Dict[str, int] | None = None   # untuk restock
_last_active_events: List[str]      = []     # untuk weather

# ─── TABEL KATEGORI & EMOJI ───────────────────────────────────────────────────
CATEGORY_ICON = {
    "seedsStock":   "🌱 Seeds",
    "gearStock":    "🛠️ Gear",
    "eggStock":     "🥚 Eggs",
    "honeyStock":   "🍯 Honey",
    "nightStock":   "🌙 Night",
    "easterStock":  "🐇 Easter",
}
CATEGORIES_ORDER = list(CATEGORY_ICON.keys())

EMOJI_MAP = {        # item emoji fallback
    "Carrot": "🥕", "Strawberry": "🍓", "Tomato": "🍅", "Blueberry": "🫐",
    "Watering Can": "🚿", "Trowel": "🛠️", "Recall Wrench": "🔧",
    "Cleaning Spray": "🧴", "Favorite Tool": "❤️", "Harvest Tool": "🚜",
    "Shovel": "⛏️", "Common Egg": "🥚",
}

EVENT_EMOJI = {      # emoji cuaca / event
    "rain": "🌧️", "thunderstorm": "⛈️", "bloodnight": "🩸",
    "meteorshower": "☄️", "disco": "🕺", "jandelstorm": "🌪️",
    "night": "🌙", "volcano": "🌋", "chocolaterain": "🍫",
    "blackhole": "🕳️", "frost": "❄️", "bloodmoonevent": "🔴",
    "gale": "🌬️", "megaharvest": "🍌", "sungod": "𓂀",
    "nightevent": "🌑", "tropicalrain": "🌴", "auroraborealis": "🌌",
    "windy": "💨", "tornado": "🌪️", "summerharvest": "⛱️", "heatwave": "♨️"
}

# ─── UTIL HTTP ────────────────────────────────────────────────────────────────
async def get_json(path: str) -> Dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()

async def fetch_stock()   -> Dict[str, Any]: return await get_json("/api/stock/GetStock")
async def fetch_weather() -> Dict[str, Any]: return await get_json(WEATHER_PATH)

# ─── DETEKSI RESTOCK ──────────────────────────────────────────────────────────
def has_restocked(current: Dict[str, int] | None) -> bool:
    global _last_timers
    if _last_timers is None:
        _last_timers = current or {}
        return False
    if not current:
        return False
    for k, v in current.items():
        if v > _last_timers.get(k, 0):
            _last_timers = current
            return True
    _last_timers = current
    return False

# ─── DETEKSI EVENT BARU ───────────────────────────────────────────────────────
def active_events_list(evt_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in evt_json.get("events", []) if e.get("isActive")]

def events_changed(current_active: List[Dict[str, Any]]) -> bool:
    global _last_active_events
    names_now = [e["name"] for e in current_active]
    if names_now != _last_active_events:
        _last_active_events = names_now
        return True
    return False

# ─── EMBED BUILDERS ───────────────────────────────────────────────────────────
def build_stock_embed(data: Dict[str, Any], restock: Dict[str, Any]) -> discord.Embed:
    now = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
    embed = discord.Embed(title=f"Grow a Garden Stock – {now}", colour=0x4caf50)
    embed.set_footer(text="WRAITH • otomatis setiap restock")
    for key in CATEGORIES_ORDER:
        items: List[Dict[str, Any]] = data.get(key, [])
        if not items: continue
        lines = []
        for item in items:
            name  = item.get("name", "?")
            qty   = item.get("value", "?")
            emoji = item.get("emoji") or EMOJI_MAP.get(name, "")
            lines.append(f"{emoji} `{qty:>3}×` {name}")
        label = CATEGORY_ICON[key]
        if restock:
            rest_key  = key.lower().replace("stock", "")
            countdown = restock.get(rest_key, {}).get("countdown")
            if countdown: label += f" ({countdown})"
        embed.add_field(name=label, value="\n".join(lines[:25]), inline=False)
    return embed

def build_weather_embed(active: List[Dict[str, Any]]) -> discord.Embed:
    now = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M")
    embed = discord.Embed(title=f"🌤️ Event Aktif – {now}", colour=0xffc107)
    if not active:
        embed.description = "_Tidak ada event/cuaca aktif saat ini._"
        return embed
    lines = []
    for ev in active:
        emoji = ev.get("emoji") or EVENT_EMOJI.get(ev["name"], "")
        rem   = ev.get("timeRemaining") or "?"
        lines.append(f"{emoji} **{ev['displayName']}** – `{rem}`")
    embed.description = "\n".join(lines)
    return embed

# ─── TASK LOOP POLLING ────────────────────────────────────────────────────────
@tasks.loop(seconds=CHECK_EVERY)
async def poll_stock():
    try:
        data   = await fetch_stock()
        rest   = await get_json("/api/stock/restock-time")
        events = await fetch_weather()
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return

    # ── KIRIM EMBED STOCK JIKA RESTOCK ────────────────────────────────────────
    if has_restocked(data.get("restockTimers")):
        ch = bot.get_channel(CHANNEL_ID)
        if ch:
            await ch.send(embed=build_stock_embed(data, rest))
            logging.info("Embed stock dikirim (restock)")

    # ── KIRIM EMBED EVENT JIKA ADA PERUBAHAN ──────────────────────────────────
    active_now = active_events_list(events)
    if events_changed(active_now) and active_now:
        ch = bot.get_channel(CHANNEL_ID)
        if ch:
            await ch.send(embed=build_weather_embed(active_now))
            logging.info("Embed weather dikirim (event aktif)")

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────
@bot.command()
async def sync(ctx):
    synced = await bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
    await ctx.send(f"Synced {len(synced)} command(s).")

@bot.command(name="weather", help="Tampilkan event/cuaca aktif saat ini")
async def weather(ctx: commands.Context):
    try:
        events  = await fetch_weather()
        active  = active_events_list(events)
        embed   = build_weather_embed(active)
        await ctx.send(embed=embed)
    except Exception as e:
        logging.error(e)
        await ctx.send("Gagal fetch weather.")
        
@bot.tree.command(name="sync", description="Paksa sync command guild")
async def sync_cmd(interaction: discord.Interaction):
    synced = await bot.tree.sync(guild=interaction.guild)
    await interaction.response.send_message(f"Synced {len(synced)} command(s).", ephemeral=True)


@bot.tree.command(name="stock", description="Tampilkan stok Grow a Garden saat ini")
async def cmd_stock(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        data   = await fetch_stock()
        rest   = await get_json("/api/stock/restock-time")
        embed  = build_stock_embed(data, rest)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logging.error(e)
        await interaction.followup.send("Gagal fetch stock.")

@bot.tree.command(name="weather", description="Tampilkan event/cuaca aktif saat ini")
async def cmd_weather(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        events = await fetch_weather()
        active = active_events_list(events)
        embed  = build_weather_embed(active)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logging.error(e)
        await interaction.followup.send("Gagal fetch weather.")

# ─── READY ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.wait_until_ready()  # ⬅️ tambahkan ini agar sync tidak terlalu cepat

    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        logging.info(f"✅ Synced {len(synced)} command(s).")
    except Exception as e:
        logging.error(f"❌ Gagal sync slash command: {e}")
    
    logging.info(f"Bot online sebagai {bot.user} (ID {bot.user.id})")
    
    if not poll_stock.is_running():
        poll_stock.start()

# ─── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Isi env TOKEN & CHANNEL_ID dulu.")
    bot.run(TOKEN)
    logging.info("Bot starting...")
