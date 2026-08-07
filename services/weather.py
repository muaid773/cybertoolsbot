import httpx
from datetime import datetime, timedelta
import os
from config import AI_API_URL, AI_API_KEY, WEATHER_API_URL, WEATHER_API_KEY
async def get_weather(lat, lon, day="today"):

    params = {
        "key": WEATHER_API_KEY,
        "q": f"{lat},{lon}",
        "days": 10,
        "lang": "ar"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(WEATHER_API_URL, params=params)

    response.raise_for_status()

    data = response.json()

    days = {
        "today": 0,
        "tomorrow": 1,
        "after_tomorrow": 2,
        "after_after_tomorrow": 3
    }

    if isinstance(day, int):
        index = day
    else:
        index = days.get(day, 0)

    forecast = data["forecast"]["forecastday"][index]

    return {
        "date": forecast["date"],
        "condition": forecast["day"]["condition"]["text"],
        "temperature": {
            "max": forecast["day"]["maxtemp_c"],
            "min": forecast["day"]["mintemp_c"]
        },
        "humidity": forecast["day"]["avghumidity"],
        "wind": forecast["day"]["maxwind_kph"],
        "rain": forecast["day"]["daily_chance_of_rain"]
    }

async def ask_groq(user_message: str, system_prompt: str):
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        "temperature": 0.7
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            AI_API_URL,
            headers=headers,
            json=data
        )

        response.raise_for_status()

        result = response.json()

        return result["choices"][0]["message"]["content"]
