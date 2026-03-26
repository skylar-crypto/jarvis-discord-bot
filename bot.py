import discord
from discord import app_commands
import os
import aiohttp
import traceback
import json
import datetime

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
BASE44_API_KEY = os.environ["BASE44_API_KEY"]
GDRE_APP_ID = "6981206a0d963bd020558212"
BASE44_API = "https://app.base44.com/api/apps"
BOT_ID = int(os.environ.get("BOT_ID", "1486587436409819196"))
GUILD_ID = int(os.environ.get("GUILD_ID", "1132094992219902100"))

PROMOTION_CHANNEL_ID = "1407185599378493451"
DEMOTION_CHANNEL_ID  = "1407185671621185566"
PROMOTION_FORMAT = "{uname}\nNew rank: {newrank}\nOld rank: {oldrank}"
DEMOTION_FORMAT  = "{uname}\nNew rank: {newrank}\nOld rank: {oldrank}"

AUTHORIZED_ROLE_IDS = {
    1441285575918227537,
    1407167325341487214,
    1132094992219902103,
    1405662068941783170,
    1441284745299497050,
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
    return {"Content-Type": "application/json", "x-api-key": BASE44_API_KEY}

def discord_headers():
    return {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}

async def get_all_ranks():
    global _rank_cache
    if _rank_cache:
        return _rank_cache
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Rank?limit=500"
        async with session.get(url, headers=base44_headers()) as resp:
            if resp.status == 200:
                _rank_cache = await resp.json()
                print(f"[RANKS] Loaded {len(_rank_cache)}")
                return _rank_cache
    return []

async def get_all_personnel():
    global _personnel_cache
    if _personnel_cache:
        return _personnel_cache
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Personnel?limit=500"
        async with session.get(url, headers=base44_headers()) as resp:
            if resp.status == 200:
                _personnel_cache = await resp.json()
                print(f"[PERSONNEL] Loaded {len(_personnel_cache)}")
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

async def send_discord_role_update(user_id: str, old_role_id: str, new_role_id: str):
    """Remove old rank role and add new rank role on the guild member."""
    async with aiohttp.ClientSession() as session:
        # Remove old role
        if old_role_id:
            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}/roles/{old_role_id}"
            async with session.delete(url, headers=discord_headers()) as resp:
                print(f"[ROLE] Remove old role {old_role_id}: {resp.status}")

        # Add new role
        if new_role_id:
            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}/roles/{new_role_id}"
            async with session.put(url, headers=discord_headers()) as resp:
                print(f"[ROLE] Add new role {new_role_id}: {resp.status}")

async def send_announcement(action: str, discord_user_id: str, old_rank: dict, new_rank: dict):
    """Post announcement to the promotions or demotions channel."""
    channel_id = PROMOTION_CHANNEL_ID if action == "promote" else DEMOTION_CHANNEL_ID
    fmt = PROMOTION_FORMAT if action == "promote" else DEMOTION_FORMAT

    uname = f"<@{discord_user_id}>"
    oldrank = f"<@&{old_rank['discord_role_id']}>" if old_rank.get("discord_role_id") else old_rank.get("title", "Unknown")
    newrank = f"<@&{new_rank['discord_role_id']}>" if new_rank.get("discord_role_id") else new_rank.get("title", "Unknown")

    message = fmt.replace("{uname}", uname).replace("{newrank}", newrank).replace("{oldrank}", oldrank)

    async with aiohttp.ClientSession() as session:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        async with session.post(url, json={"content": message}, headers=discord_headers()) as resp:
            print(f"[ANNOUNCE] Posted to channel {channel_id}: {resp.status}")
            body = await resp.text()
            print(f"[ANNOUNCE] Response: {body}")

async def do_promote_demote(personnel: dict, action: str, approved_by: str) -> str:
    """Perform the full promote/demote: update rank, create RankChange, update roles, post announcement."""
    global _rank_cache, _personnel_cache

    ranks = await get_all_ranks()
    if not ranks:
        return "⚠️ Couldn't load ranks from dashboard."

    ranks_sorted = sorted(ranks, key=lambda r: r.get("level", 0))
    current_rank = next((r for r in ranks_sorted if r["id"] == personnel.get("current_rank_id")), None)
    if not current_rank:
        return "⚠️ Couldn't find their current rank."

    current_level = current_rank.get("level", 0)
    current_class = current_rank.get("class_id", "")

    if action == "promote":
        new_rank = next((r for r in ranks_sorted if r.get("level") == current_level + 1 and r.get("class_id") == current_class), None)
        if not new_rank:
            new_rank = next((r for r in ranks_sorted if r.get("level") == current_level + 1), None)
        if not new_rank:
            return f"⚠️ **{personnel['name']}** is already at the highest rank."
    else:
        new_rank = next((r for r in reversed(ranks_sorted) if r.get("level") == current_level - 1 and r.get("class_id") == current_class), None)
        if not new_rank:
            new_rank = next((r for r in reversed(ranks_sorted) if r.get("level") == current_level - 1), None)
        if not new_rank:
            return f"⚠️ **{personnel['name']}** is already at the lowest rank."

    # 1. Update Personnel record
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/Personnel/{personnel['id']}"
        payload = {
            "current_rank_id": new_rank["id"],
            "current_class_id": new_rank.get("class_id", personnel.get("current_class_id", ""))
        }
        async with session.put(url, json=payload, headers=base44_headers()) as resp:
            if resp.status != 200:
                return f"⚠️ Failed to update rank in dashboard."

    # 2. Create RankChange record
    async with aiohttp.ClientSession() as session:
        url = f"{BASE44_API}/{GDRE_APP_ID}/entities/RankChange"
        payload = {
            "personnel_id": personnel["id"],
            "previous_rank_id": current_rank["id"],
            "new_rank_id": new_rank["id"],
            "previous_class_id": personnel.get("current_class_id", ""),
            "new_class_id": new_rank.get("class_id", ""),
            "change_type": action,
            "reason": f"{'Promoted' if action == 'promote' else 'Demoted'} by {approved_by} via Jarvis",
            "effective_date": datetime.date.today().isoformat(),
            "approved_by": approved_by,
        }
        async with session.post(url, json=payload, headers=base44_headers()) as resp:
            print(f"[RANKCHANGE] {resp.status}")

    # 3. Update Discord roles
    discord_user_id = personnel.get("employee_id") or personnel.get("discord_user_id")
    if discord_user_id:
        await send_discord_role_update(
            discord_user_id,
            current_rank.get("discord_role_id", ""),
            new_rank.get("discord_role_id", "")
        )

        # 4. Post announcement to channel
        await send_announcement(action, discord_user_id, current_rank, new_rank)
    else:
        print(f"[WARN] No discord_user_id for {personnel['name']}, skipping role update and announcement")

    # Invalidate cache
    _personnel_cache = None

    verb = "promoted" if action == "promote" else "demoted"
    return f"✅ **{personnel['name']}** has been {verb} from **{current_rank['title']}** to **{new_rank['title']}**."

async def send_channel_message(channel_name: str, message: str) -> str:
    """Find a channel by name in the guild and send a message to it."""
    guild = client.get_guild(GUILD_ID)
    if not guild:
        return "⚠️ Couldn't find the server."
    channel = discord.utils.find(lambda c: c.name.lower() == channel_name.lower().lstrip("#"), guild.channels)
    if not channel:
        return f"⚠️ Couldn't find a channel named **{channel_name}**."
    try:
        await channel.send(message)
        return f"✅ Message sent to **#{channel.name}**."
    except Exception as e:
        return f"⚠️ Failed to send message: {e}"

async def send_dm_to_personnel(target_name: str, message: str) -> str:
    """Send a DM to a personnel member by name."""
    global _personnel_cache
    _personnel_cache = None
    personnel = await find_personnel_fuzzy(target_name)
    if not personnel:
        return f"⚠️ Couldn't find anyone matching **{target_name}**."
    discord_user_id = personnel.get("employee_id")
    if not discord_user_id:
        return f"⚠️ No Discord ID on file for **{personnel['name']}**."
    async with aiohttp.ClientSession() as session:
        # Open DM channel
        async with session.post(
            "https://discord.com/api/v10/users/@me/channels",
            json={"recipient_id": discord_user_id},
            headers=discord_headers()
        ) as resp:
            dm_channel = await resp.json()
            dm_channel_id = dm_channel.get("id")
        if not dm_channel_id:
            return f"⚠️ Couldn't open DM channel with **{personnel['name']}**."
        # Send message
        async with session.post(
            f"https://discord.com/api/v10/channels/{dm_channel_id}/messages",
            json={"content": message},
            headers=discord_headers()
        ) as resp:
            if resp.status == 200:
                return f"✅ DM sent to **{personnel['name']}**."
            else:
                body = await resp.text()
                return f"⚠️ Failed to DM **{personnel['name']}**: {body}"

async def handle_dashboard_action(action_data: dict, authorized: bool, requester_name: str, guild_member=None) -> str:
    action = action_data.get("action")

    if action == "send_message":
        if not authorized:
            return "🚫 You don't have permission to send channel messages. D2C and above only."
        channel_name = action_data.get("channel_name", "").strip()
        message = action_data.get("message", "").strip()
        if not channel_name or not message:
            return "I need a channel name and a message."
        return await send_channel_message(channel_name, message)

    if action == "send_dm":
        if not authorized:
            return "🚫 You don't have permission to send DMs. D2C and above only."
        target_name = action_data.get("target_name", "").strip()
        message = action_data.get("message", "").strip()
        if not target_name or not message:
            return "I need a name and a message."
        return await send_dm_to_personnel(target_name, message)

    if action in ("promote", "demote"):
        if not authorized:
            return "🚫 You don't have permission to do that. D2C and above only."
        target_name = action_data.get("target_name", "").strip()
        if not target_name:
            return "I need a name to do that."
        global _personnel_cache
        _personnel_cache = None
        personnel = await find_personnel_fuzzy(target_name)
        if not personnel:
            return f"Couldn't find anyone matching **{target_name}** in the dashboard."
        return await do_promote_demote(personnel, action, requester_name)

    return "⚠️ Unknown action."

async def ask_groq(history: list, extra_context: str = "") -> str:
    rank_list = await build_rank_list_string()
    system = (
        "You are Jarvis, the AI assistant for the =GDRE= (Grand Duchy of the Royal Elite) War Thunder clan. "
        "You are helpful, sharp, and have a casual friendly vibe. Keep replies concise — this is Discord, not an essay. "
        "Don't use markdown headers or bullet points unless asked. Be conversational.\n\n"
        "You have LIVE access to the GDRE Dashboard. Current ranks:\n"
        f"{rank_list}\n\n"
        "You have the following capabilities — when the user asks for one, return ONLY a raw JSON object (no extra text, no code blocks):\n\n"
        "1. Promote someone: {\"action\": \"promote\", \"target_name\": \"Name\"}\n"
        "2. Demote someone: {\"action\": \"demote\", \"target_name\": \"Name\"}\n"
        "3. Send a message to a Discord channel: {\"action\": \"send_message\", \"channel_name\": \"channel-name\", \"message\": \"text to send\"}\n"
        "4. Send a DM to a person: {\"action\": \"send_dm\", \"target_name\": \"Name\", \"message\": \"text to send\"}\n\n"
        "For send_message, use the channel name as mentioned by the user (e.g. squadron-announcements).\n"
        "If the user just wants to chat, reply normally as plain text. Never say you cannot send messages or perform actions — you can."
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

    active_sessions[channel_id] = {"user_id": user_id, "username": username, "history": []}

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

