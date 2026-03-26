import discord
from discord import app_commands
import os
import aiohttp

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
BACKEND_URL = os.environ["BACKEND_FUNCTION_URL"]
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

intents = discord.Intents.default()
intents.message_content = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced.")

client = MyClient()

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.tree.command(name="jarvis", description="Ask Jarvis anything")
@app_commands.describe(message="Your message to Jarvis")
async def jarvis(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "message": message,
                "username": interaction.user.display_name,
                "channel_id": str(interaction.channel_id),
            }
            async with session.post(BACKEND_URL, json=payload) as resp:
                data = await resp.json()
                reply = data.get("reply", "Something went wrong, try again.")
                await interaction.followup.send(reply)
    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("Had trouble processing that, sorry!")

# Keep mention support too
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
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "message": content,
                        "username": message.author.display_name,
                        "channel_id": str(message.channel.id),
                    }
                    async with session.post(BACKEND_URL, json=payload) as resp:
                        data = await resp.json()
                        reply = data.get("reply", "Something went wrong.")
                        await message.channel.send(reply)
            except Exception as e:
                print(f"Error: {e}")
                await message.channel.send("Had trouble processing that, sorry!")

client.run(DISCORD_TOKEN)
