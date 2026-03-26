import discord
import os
import aiohttp

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
BACKEND_URL = os.environ["BACKEND_FUNCTION_URL"]
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author.bot:
        return

    # Check if the bot is mentioned
    if client.user in message.mentions:
        # Strip the mention from the message
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
                        if not data.get("ok"):
                            await message.channel.send("Something went wrong, try again.")
            except Exception as e:
                print(f"Error: {e}")
                await message.channel.send("Had trouble processing that, sorry!")

client.run(DISCORD_TOKEN)

