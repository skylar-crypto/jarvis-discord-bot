import discord
from discord import app_commands
import os
import aiohttp
import traceback
import json

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GDRE_APP_ID = "6981206a0d963bd020558212"
BASE44_API = "https://app.base44.com/api/apps"
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

# D2C and above — allowed to trigger dashboard actions
AUTHORIZED_ROLE_IDS = {
    1441285575918227537,  # GDRE | D2C 1-04
    1441285206148644935,  # GDRE | D1C 1-03 (below D2C, excluded — just D2C+)
    1407167325341487214,  # GDRE - Executive Officer
    1132094992219902103,  # GDRE - Commanding Officer
    1405662068941783170,  # GDRE - Commanding Admiral
    1441284745299497050,  # GDRE | Directive Class (role)
}
# Remove D1C — only D2C and above
AUTHORIZED_ROLE_IDS.discard(1441285206148644935)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# active_sessions: { channel_id: { user_id, history, username } }
active_sessions = {}

END_PHRASES = {"end", "stop", "bye", "goodbye", "quit", "exit", "close", "done"}

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
    "Don't use markdown headers or bullet points unless asked. Be conversational.\n\n"
    "You can also perform dashboard actions like promoting or demoting personnel — but only for authorized users (D2C and above). "
    "When a user asks to promote or demote someone, extract the target's name and the new rank/class, then return a JSON action like:\n"
    "{\"action\": \"promote\", \"target_name\": \"PlayerName\", \"new_rank_title\": \"RE | CDR 0-5\"}\n"
    "or {\"action\": \"demote\", \"target_name\": \"PlayerName\", \"new_rank_title\": \"RE | LT 0-3\"}\n"
    "ONLY return the JSON if a dashboard action is needed. Otherwise just reply normally as text."
)

def is_authorized(member: discord.Member) -> bool:
    return any(role.id in AUTHORIZED_ROLE_IDS for role in member.roles)

async def ask_groq(history: list) -> str:
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 400,
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

async def find_personnel(name: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Personnel/filter"
        async with session.post(url, json={"name": name}, headers={"Content-Type": "application/json"}) as resp:
            if resp.status == 200:
                data = await resp.json()
                records = data.get("records", [])
                return records[0] if records else None
    return None

async def find_rank_by_title(title: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Rank/filter"
        async with session.post(url, json={"title": title}, headers={"Content-Type": "application/json"}) as resp:
            if resp.status == 200:
                data = await resp.json()
                records = data.get("records", [])
                return records[0] if records else None
    return None

async def update_personnel_rank(personnel_id: str, new_rank_id: str, new_class_id: str) -> bool:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Personnel/{personnel_id}"
        async with session.put(url, json={"current_rank_id": new_rank_id, "current_class_id": new_class_id}, headers={"Content-Type": "application/json"}) as resp:
            return resp.status == 200

async def handle_dashboard_action(action_data: dict, authorized: bool, channel) -> str:
    if not authorized:
        return "🚫 You don't have permission to perform dashboard actions. D2C and above only."

    action = action_data.get("action")
    target_name = action_data.get("target_name", "").strip()
    new_rank_title = action_data.get("new_rank_title", "").strip()

    if not target_name or not new_rank_title:
        return "I need both a name and a rank to do that. Try again with more detail."

    personnel = await find_personnel(target_name)
    if not personnel:
        return f"Couldn't find **{target_name}** in the dashboard. Double-check the name."

    new_rank = await find_rank_by_title(new_rank_title)
    if not new_rank:
        return f"Couldn't find rank **{new_rank_title}** in the dashboard. Check the rank title."

    success = await update_personnel_rank(personnel["id"], new_rank["id"], new_rank.get("class_id", ""))

    if success:
        verb = "promoted" if action == "promote" else "demoted"
        return f"✅ **{target_name}** has been {verb} to **{new_rank_title}**."
    else:
        return f"⚠️ Something went wrong updating the dashboard. Try again."

@client.event
async def on_ready():
    print(f"[BOOT] Logged in as {client.user}")

@client.tree.command(name="jarvis", description="Start a conversation with Jarvis")
async def jarvis(interaction: discord.Interaction):
    user_id = interaction.user.id
    channel_id = interaction.channel_id
    username = interaction.user.display_name

    print(f"[CMD] /jarvis from {username}")

    active_sessions[channel_id] = {
        "user_id": user_id,
        "username": username,
        "history": []
    }

    await interaction.response.defer(thinking=True)
    try:
        greeting_prompt = f"The user's name is {username}. Greet them warmly and let them know you're ready to help. Keep it short and casual."
        history = [{"role": "user", "content": greeting_prompt}]
        greeting = await ask_groq(history)

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
    session = active_sessions.get(channel_id)

    if session and session["user_id"] == user_id:
        content = message.content.strip()

        if content.lower() in END_PHRASES or content.lower().startswith("end"):
            del active_sessions[channel_id]
            await message.channel.send(f"Alright {message.author.display_name}, catch you later! 👋")
            return

        async with message.channel.typing():
            try:
                authorized = is_authorized(message.author) if isinstance(message.author, discord.Member) else False
                session["history"].append({"role": "user", "content": content})
                reply = await ask_groq(session["history"])

                # Check if Groq returned a JSON action
                stripped = reply.strip()
                if stripped.startswith("{") and "action" in stripped:
                    try:
                        action_data = json.loads(stripped)
                        result = await handle_dashboard_action(action_data, authorized, message.channel)
                        session["history"].append({"role": "assistant", "content": result})
                        await message.channel.send(result)
                        return
                    except json.JSONDecodeError:
                        pass

                session["history"].append({"role": "assistant", "content": reply})
                await message.channel.send(reply)
            except Exception as e:
                print(f"[ERROR] {traceback.format_exc()}")
                await message.channel.send("Had a hiccup, try again!")
        return

    # Fallback: respond to @mentions outside sessions
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
