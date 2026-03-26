import discord
from discord import app_commands
import os
import aiohttp
import traceback
import json

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

intents = discord.Intents.default()
intents.message_content = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("[BOOT] Slash commands synced.")

client = MyClient()

SYSTEM_PROMPT = (
    "You are Jarvis, the AI assistant for the =GDRE= (Grand Duchy of the Royal Elite) War Thunder clan. "
    "You are helpful, sharp, and have a casual friendly vibe. Keep replies concise — this is Discord, not an essay. "
    "You know about the clan's structure: Enlisted, Officer, Command, Overseer, Superintendent, Directive, and Ownership classes. "
    "Don't use markdown headers or bullet points unless asked. Be conversational."
)

async def ask_groq(username: str, message: str) -> str:
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{username} said: {message}"}
            ]
        }
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

@client.event
async def on_ready():
    print(f"[BOOT] Logged in as {client.user}")

@client.tree.command(name="jarvis", description="Ask Jarvis anything")
@app_commands.describe(message="Your message to Jarvis")
async def jarvis(interaction: discord.Interaction, message: str):
    print(f"[CMD] /jarvis from {interaction.user} — '{message}'")
    await interaction.response.defer(thinking=True)
    try:
        reply = await ask_groq(interaction.user.display_name, message)
        await interaction.followup.send(reply)
    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        await interaction.followup.send(f"Had trouble with that — {str(e)}")

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if client.user in message.mentions:
        content = message.content.replace(f"<@{BOT_ID}>", "").replace(f"<@!{BOT_ID}>", "").strip()
        if not content:
            content = "hey"
        async with message.channel.typing():
            try:
                reply = await ask_groq(message.author.display_name, content)
                await message.channel.send(reply)
            except Exception as e:
                print(f"[ERROR] {traceback.format_exc()}")
                await message.channel.send(f"Had trouble with that — {str(e)}")

client.run(DISCORD_TOKEN)
