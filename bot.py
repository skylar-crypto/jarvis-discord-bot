import discord
from discord import app_commands
import os
import aiohttp
import traceback

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
BACKEND_URL = os.environ["BACKEND_FUNCTION_URL"]
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

print(f"[BOOT] BACKEND_URL = {BACKEND_URL}")

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

@client.event
async def on_ready():
    print(f"[BOOT] Logged in as {client.user}")

@client.tree.command(name="jarvis", description="Ask Jarvis anything")
@app_commands.describe(message="Your message to Jarvis")
async def jarvis(interaction: discord.Interaction, message: str):
    print(f"[CMD] /jarvis from {interaction.user} — '{message}'")
    await interaction.response.defer(thinking=True)
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "message": message,
                "username": interaction.user.display_name,
                "channel_id": str(interaction.channel_id),
            }
            print(f"[CMD] Sending to backend: {BACKEND_URL}")
            async with session.post(BACKEND_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"[CMD] Backend status: {resp.status}")
                text = await resp.text()
                print(f"[CMD] Backend response: {text}")
                import json
                data = json.loads(text)
                reply = data.get("reply", "Something went wrong, try again.")
                await interaction.followup.send(reply)
    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        await interaction.followup.send(f"Had trouble processing that, sorry! Error: {str(e)}")

client.run(DISCORD_TOKEN)
