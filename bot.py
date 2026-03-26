import discord
from discord import app_commands
import os
import aiohttp
import traceback
import json

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
BASE44_API_KEY = os.environ["BASE44_API_KEY"]
GDRE_APP_ID = "6981206a0d963bd020558212"
BASE44_API = "https://app.base44.com/api/apps"
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))

# Backend function URLs (the GDRE Dashboard functions)
PROMOTE_URL = "https://app.base44.com/api/apps/69c41dac15cf7ec6ffe7c14a/functions/promotePersonnel"
DEMOTE_URL  = "https://app.base44.com/api/apps/69c41dac15cf7ec6ffe7c14a/functions/demotePersonnel"

AUTHORIZED_ROLE_IDS = {
    1441285575918227537,  # GDRE | D2C 1-04
    1407167325341487214,  # GDRE - Executive Officer
    1132094992219902103,  # GDRE - Commanding Officer
    1405662068941783170,  # GDRE - Commanding Admiral
    1441284745299497050,  # GDRE | Directive Class (role)
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

active_sessions = {}
END_PHRASES = {"end", "stop", "bye", "goodbye", "quit", "exit", "close", "done"}

_rank_cache = None
_personnel_cache = None

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("[BOOT] Slash commands synced.")

client = MyClient()

def base44_headers():
    return {
        "Content-Type": "application/json",
        "x-api-key": BASE44_API_KEY
    }

async def get_all_ranks():
    global _rank_cache
    if _rank_cache:
        return _rank_cache
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Rank?limit=500"
        async with session.get(url, headers=base44_headers()) as resp:
            print(f"[RANKS] Status: {resp.status}")
            if resp.status == 200:
                _rank_cache = await resp.json()
                print(f"[RANKS] Loaded {len(_rank_cache)} ranks")
                return _rank_cache
    return []

async def get_all_personnel():
    global _personnel_cache
    if _personnel_cache:
        return _personnel_cache
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Personnel?limit=500"
        async with session.get(url, headers=base44_headers()) as resp:
            print(f"[PERSONNEL] Status: {resp.status}")
            if resp.status == 200:
                _personnel_cache = await resp.json()
                print(f"[PERSONNEL] Loaded {len(_personnel_cache)} records")
                return _personnel_cache
    return []

async def find_personnel_fuzzy(name: str):
    records = await get_all_personnel()
    name_lower = name.lower().strip()
    for r in records:
        if r.get("name", "").lower() == name_lower:
            return r
    for r in records:
        if r.get("name", "").lower().startswith(name_lower):
            return r
    for r in records:
        if name_lower in r.get("name", "").lower():
            return r
    return None

async def get_rank_by_id(rank_id: str):
    records = await get_all_ranks()
    for r in records:
        if r.get("id") == rank_id:
            return r
    return None

async def build_rank_list_string():
    ranks = await get_all_ranks()
    if not ranks:
        return "No ranks found."
    sorted_ranks = sorted(ranks, key=lambda r: r.get("level", 0))
    return "\n".join([f"- {r['title']} (level {r.get('level','?')})" for r in sorted_ranks])

def is_authorized(member: discord.Member) -> bool:
    return any(role.id in AUTHORIZED_ROLE_IDS for role in member.roles)

async def call_dashboard_function(url: str, personnel_id: str, approved_by: str, reason: str = "") -> dict:
    """Call the GDRE Dashboard promote/demote backend function."""
    async with aiohttp.ClientSession() as session:
        payload = {
            "personnel_id": personnel_id,
            "approved_by": approved_by,
            "reason": reason or f"Actioned by {approved_by} via Jarvis"
        }
        async with session.post(url, json=payload, headers=base44_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
            print(f"[DASHBOARD] Function call status: {resp.status}")
            data = await resp.json()
            print(f"[DASHBOARD] Response: {data}")
            return {"status": resp.status, "data": data}

async def handle_dashboard_action(action_data: dict, authorized: bool, requester_name: str) -> str:
    if not authorized:
        return "🚫 You don't have permission to perform dashboard actions. D2C and above only."

    action = action_data.get("action")
    target_name = action_data.get("target_name", "").strip()

    if not target_name:
        return "I need a name to do that."

    # Always fetch fresh
    global _personnel_cache
    _personnel_cache = None

    personnel = await find_personnel_fuzzy(target_name)
    if not personnel:
        return f"Couldn't find anyone matching **{target_name}** in the dashboard."

    url = PROMOTE_URL if action == "promote" else DEMOTE_URL
    result = await call_dashboard_function(url, personnel["id"], requester_name)

    if result["status"] == 200:
        msg = result["data"].get("message", "Done.")
        return f"✅ {msg}"
    else:
        err = result["data"].get("error", "Unknown error")
        return f"⚠️ {err}"

async def ask_groq(history: list, extra_context: str = "") -> str:
    rank_list = await build_rank_list_string()
    system = (
        "You are Jarvis, the AI assistant for the =GDRE= (Grand Duchy of the Royal Elite) War Thunder clan. "
        "You are helpful, sharp, and have a casual friendly vibe. Keep replies concise — this is Discord, not an essay. "
        "Don't use markdown headers or bullet points unless asked. Be conversational.\n\n"
        "You have LIVE access to the GDRE Dashboard. Current ranks:\n"
        f"{rank_list}\n\n"
        "When a user asks to promote or demote someone, return ONLY a raw JSON object (no extra text, no code blocks):\n"
        "{\"action\": \"promote\", \"target_name\": \"NameAsTyped\"}\n"
        "or {\"action\": \"demote\", \"target_name\": \"NameAsTyped\"}\n"
        "The dashboard handles all the rank logic automatically — you just need the name and action. "
        "If the user just wants to chat, reply normally as plain text."
    )
    if extra_context:
        system += f"\n\nContext: {extra_context}"

    async with aiohttp.ClientSession() as session:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 400,
            "messages": [{"role": "system", "content": system}] + history
        }
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

@client.event
async def on_ready():
    print(f"[BOOT] Logged in as {client.user}")
    await get_all_ranks()
    await get_all_personnel()

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

                # Pass current rank context if personnel name is mentioned
                extra_context = ""
                personnel_all = await get_all_personnel()
                for p in personnel_all:
                    pname = p.get("name", "").lower()
                    if pname and pname in content.lower():
                        current_rank = await get_rank_by_id(p.get("current_rank_id", ""))
                        if current_rank:
                            extra_context = f"{p['name']}'s current rank is '{current_rank['title']}' (level {current_rank.get('level','?')})."
                        break

                session["history"].append({"role": "user", "content": content})
                reply = await ask_groq(session["history"], extra_context)

                # Strip code block if present
                stripped = reply.strip()
                if stripped.startswith("```"):
                    stripped = stripped.strip("`").strip()
                    if stripped.startswith("json"):
                        stripped = stripped[4:].strip()

                if stripped.startswith("{") and "action" in stripped:
                    try:
                        action_data = json.loads(stripped)
                        result = await handle_dashboard_action(action_data, authorized, message.author.display_name)
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

    # Fallback: @mentions outside sessions
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
