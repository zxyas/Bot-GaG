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
API_BASE = "https://3dbcb2fc-9b87-490a-9955-14170d903b2b-00-24ka2fj5mlj0t.worf.replit.dev"  # URL API /stock
CHECK_EVERY = 10  # detik interval polling API
LOG_LEVEL = "INFO"  # DEBUG/INFO/WARNING/ERROR

# ────────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                    format="[%(asctime)s] %(levelname)s: %(message)s")

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


def build_embed(data: Dict[str, Any]) -> discord.Embed:
    wib = timezone(timedelta(hours=7))
    now = datetime.now(wib).strftime('%H:%M')
    embed = discord.Embed(title=f"Grow a Garden Stock – {now}",
                          colour=0x4caf50)
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
        embed.add_field(name=CATEGORY_ICON[key],
                        value="\n".join(lines[:25]),
                        inline=False)
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
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return

    if not has_restocked(data.get("restockTimers")):
        return  # belum restock, diam

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        logging.warning("CHANNEL_ID tidak valid atau bot tak punya akses.")
        return

    embed = build_embed(data)
    await channel.send(content="", embed=embed)
    logging.info("Embed restock dikirim → Discord")


# Slash command manual
@bot.tree.command(name="stock",
                  description="Tampilkan stok Grow a Garden saat ini")
async def stock_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        data = await fetch_stock()
    except Exception as e:
        await interaction.followup.send(f"Gagal fetch: {e}")
        return
    await interaction.followup.send(embed=build_embed(data))


# ────────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Mohon isi TOKEN dan CHANNEL_ID.")
    bot.run(TOKEN)
