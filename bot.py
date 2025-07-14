import logging
import os
from typing import Dict, Any, List

import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

# ────────────────────────────────────────────────────────────────────────────────
# KONFIGURASI — ISI DI SINI
# ────────────────────────────────────────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")  # token bot
GUILD_ID = 1221173165179277425  # ganti dengan ID server Discord kamu
CHANNEL_ID = 1393911452334555146  # channel tempat embed dikirim
API_BASE = "https://grow-a-garden-api-production-ec78.up.railway.app"  # URL API /stock
CHECK_EVERY = 10  # detik interval polling API
LOG_LEVEL = "INFO"  # DEBUG/INFO/WARNING/ERROR

# ────────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL), format="[%(asctime)s] %(levelname)s: %(message)s"
)

INTENTS = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Cache untuk mendeteksi restock
_last_timers: Dict[str, int] | None = None

# Ikon kategori dan urutan tampil
CATEGORY_ICON = {
    "seedsStock": "🌱 Seeds",
    "gearStock": "🛠️ Gear",
    "eggStock": "🥚 Eggs",
    "honeyStock": "🍯 Honey",
    "nightStock": "🌙 Night",
    "easterStock": "🐇 Easter",
}
CATEGORIES_ORDER = list(CATEGORY_ICON.keys())

# Emoji manual fallback
EMOJI_MAP = {
    "Carrot": "🥕",
    "Strawberry": "🍓",
    "Tomato": "🍅",
    "Blueberry": "🫐",
    "Watermelon": "🍉",
    "Watering Can": "🚿",
    "Trowel": "🛠️",
    "Recall Wrench": "🔧",
    "Cleaning Spray": "🧴",
    "Favorite Tool": "❤️",
    "Harvest Tool": "🚜",
    "Shovel": "⛏️",
    "Common Egg": "🥚",
    "Apple": "🍎",
    "Magnifying Glass": "🔎",
}


# ────────────────────────────────────────────────────────────────────────────────
# UTIL
# ────────────────────────────────────────────────────────────────────────────────
async def fetch_stock() -> Dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}/api/stock/GetStock"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()


def has_restocked(current: Dict[str, int] | None) -> bool:
    """Return True only when any timer increases (i.e., resets)."""
    global _last_timers
    if _last_timers is None:
        _last_timers = current or {}
        return False  # first call – don't send
    if not current:
        return False
    for key, value in current.items():
        prev = _last_timers.get(key, 0)
        if value > prev:  # timer reset (count‑up relative to countdown model)
            _last_timers = current
            return True
    _last_timers = current
    return False


def build_embed(
    data: Dict[str, Any], restock_times: Dict[str, Any] = None
) -> discord.Embed:
    wib = timezone(timedelta(hours=7))
    now = datetime.now(wib).strftime("%H:%M")
    embed = discord.Embed(title=f"Grow a Garden Stock – {now}", colour=0x4CAF50)
    embed.set_footer(text="WRAITH • Dikirim Setiap Restock")
    for key in CATEGORIES_ORDER:
        items: List[Dict[str, Any]] = data.get(key, [])
        if not items:
            continue

        lines = []
        for item in items:
            name = item.get("name", "?")
            qty = item.get("value", "?")
            emoji = item.get("emoji") or EMOJI_MAP.get(name, "")
            lines.append(f"{emoji} `{qty:>3}×` {name}")

        # Ambil countdown jika tersedia
        label = CATEGORY_ICON[key]
        if restock_times:
            restock_key = key.lower().replace("stock", "")
            time_left = restock_times.get(restock_key, {}).get("countdown")
            if time_left:
                label += f" ({time_left})"

        embed.add_field(name=label, value="\n".join(lines[:25]), inline=False)

    return embed


# ────────────────────────────────────────────────────────────────────────────────
# EVENTS & TASKS
# ────────────────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    logging.info(f"Bot online sebagai {bot.user} (ID {bot.user.id})")
    if not poll_stock.is_running():
        poll_stock.start()


@tasks.loop(seconds=CHECK_EVERY)
async def poll_stock():
    try:
        data = await fetch_stock()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE.rstrip('/')}/api/stock/restock-time"
            ) as r:
                restock_times = await r.json()
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return

    if not has_restocked(data.get("restockTimers")):
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logging.warning("CHANNEL_ID salah atau bot tak punya akses.")
        return

    await channel.send(content="", embed=build_embed(data, restock_times))
    logging.info("Embed restock dikirim → Discord")


# Slash command manual
@bot.tree.command(name="stock", description="Lihat stock saat ini")
async def stock_command(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        data = await fetch_stock()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE.rstrip('/')}/api/stock/restock-time"
            ) as r:
                restock_times = await r.json()

        embed = build_embed(data, restock_times)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logging.error(f"/stock error: {e}")
        await interaction.followup.send("Gagal mengambil data stock.")


# ────────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Mohon isi TOKEN dan CHANNEL_ID.")
    bot.run(TOKEN)
