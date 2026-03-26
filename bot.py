import discord
from discord import app_commands
import os
import aiohttp
import traceback

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

intents = discord.Intents.default()
intents.message_content = True

# active_sessions: { channel_id: { user_id, history: [...] } }
active_sessions = {}

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

END_PHRASES = {"end", "stop", "bye", "goodbye", "quit", "exit", "close", "done"}

async def ask_groq(history: list) -> str:
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 300,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + history
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

@client.tree.command(name="jarvis", description="Start a conversation with Jarvis")
async def jarvis(interaction: discord.Interaction):
    user_id = interaction.user.id
    channel_id = interaction.channel_id
    username = interaction.user.display_name

    print(f"[CMD] /jarvis from {username} in channel {channel_id}")

    # Start a new session for this channel/user
    active_sessions[channel_id] = {
        "user_id": user_id,
        "history": []
    }

    await interaction.response.defer(thinking=True)
    try:
        # Greeting turn
        greeting_prompt = f"The user's name is {username}. Greet them warmly and let them know you're ready to chat. Keep it short."
        history = [{"role": "user", "content": greeting_prompt}]
        greeting = await ask_groq(history)

        # Store greeting in history
        active_sessions[channel_id]["history"] = [
            {"role": "user", "content": greeting_prompt},
            {"role": "assistant", "content": greeting}
        ]

        await interaction.followup.send(f"{greeting}\n\n*Say **end** to close the conversation.*")
    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        del active_sessions[channel_id]
        await interaction.followup.send("Couldn't start a session, sorry!")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = message.channel.id
    user_id = message.author.id

    # Check if there's an active session in this channel for this user
    session = active_sessions.get(channel_id)
    if session and session["user_id"] == user_id:
        content = message.content.strip()

        # Check for end phrase
        if content.lower() in END_PHRASES or content.lower().startswith("end"):
            del active_sessions[channel_id]
            await message.channel.send(f"Alright {message.author.display_name}, catch you later! 👋")
            return

        # Continue conversation
        async with message.channel.typing():
            try:
                session["history"].append({"role": "user", "content": content})
                reply = await ask_groq(session["history"])
                session["history"].append({"role": "assistant", "content": reply})
                await message.channel.send(reply)
            except Exception as e:
                print(f"[ERROR] {traceback.format_exc()}")
                await message.channel.send("Had a hiccup, try again!")
        return

    # Fallback: respond to mentions outside of sessions
    if client.user in message.mentions:
        content = message.content.replace(f"<@{BOT_ID}>", "").replace(f"<@!{BOT_ID}>", "").strip()
        if not content:
            content = "hey"
        async with message.channel.typing():
            try:
                reply = await ask_groq([{"role": "user", "content": f"{message.author.display_name} said: {content}"}])
                await message.channel.send(reply)
            except Exception as e:
                print(f"[ERROR] {traceback.format_exc()}")
                await message.channel.send("Had trouble with that!")

client.run(DISCORD_TOKEN)
