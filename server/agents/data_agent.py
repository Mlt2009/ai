"""Data Agent — real-time information: weather, time, news, crypto prices.

Uses only free, key-less public APIs so it works out of the box.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

from .. import config
from .base import BaseAgent, tool

WMO_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "icy fog", 51: "light drizzle", 61: "light rain",
    63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 95: "thunderstorm",
}


class DataAgent(BaseAgent):
    name = "data"
    description = "Fetches real-time data: weather and forecasts, current date/time, top news headlines, and cryptocurrency prices."

    @tool(
        "Get current weather and today's forecast. Uses the configured home "
        "location unless a city is given.",
        city={"type": "string", "description": "Optional city name to look up", "required": False},
    )
    async def weather(self, city: str = ""):
        async with httpx.AsyncClient(timeout=10) as c:
            lat, lon, place = config.WEATHER_LAT, config.WEATHER_LON, "home"
            if city:
                geo = await c.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1},
                )
                results = geo.json().get("results") or []
                if not results:
                    return {"error": f"city {city!r} not found"}
                lat, lon, place = results[0]["latitude"], results[0]["longitude"], results[0]["name"]
            r = await c.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "forecast_days": 3, "timezone": "auto",
                },
            )
            d = r.json()
            cur, daily = d.get("current", {}), d.get("daily", {})
            return {
                "place": place,
                "now": {
                    "temp_c": cur.get("temperature_2m"),
                    "feels_like_c": cur.get("apparent_temperature"),
                    "humidity_pct": cur.get("relative_humidity_2m"),
                    "wind_kmh": cur.get("wind_speed_10m"),
                    "conditions": WMO_CODES.get(cur.get("weather_code"), "unknown"),
                },
                "forecast": [
                    {"date": daily.get("time", [None] * 3)[i],
                     "high_c": daily.get("temperature_2m_max", [None] * 3)[i],
                     "low_c": daily.get("temperature_2m_min", [None] * 3)[i],
                     "rain_chance_pct": daily.get("precipitation_probability_max", [None] * 3)[i]}
                    for i in range(min(3, len(daily.get("time", []))))
                ],
            }

    @tool("Get the current local date and time.")
    async def current_time(self):
        now = datetime.now().astimezone()
        return {
            "iso": now.isoformat(timespec="seconds"),
            "readable": now.strftime("%A, %B %d %Y, %I:%M %p"),
            "timezone": str(now.tzinfo),
        }

    @tool(
        "Get top news headlines (Hacker News front page, plus BBC world news RSS).",
        count={"type": "integer", "description": "How many headlines (default 5)", "required": False},
    )
    async def news(self, count: int = 5):
        count = max(1, min(15, count))
        headlines = []
        async with httpx.AsyncClient(timeout=10) as c:
            try:
                rss = await c.get("https://feeds.bbci.co.uk/news/world/rss.xml")
                titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", rss.text)
                headlines += [{"source": "BBC", "title": t} for t in titles[1:count + 1]]
            except Exception:
                pass
            try:
                ids = (await c.get("https://hacker-news.firebaseio.com/v0/topstories.json")).json()[:count]
                for i in ids:
                    item = (await c.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")).json()
                    headlines.append({"source": "HN", "title": item.get("title")})
            except Exception:
                pass
        return headlines or {"error": "news sources unreachable"}

    @tool(
        "Get live cryptocurrency prices in USD.",
        coins={"type": "string", "description": "Comma-separated coin ids, e.g. bitcoin,ethereum", "required": False},
    )
    async def crypto_prices(self, coins: str = "bitcoin,ethereum"):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coins, "vs_currencies": "usd", "include_24hr_change": "true"},
            )
            return r.json()
