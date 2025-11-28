import os
import time
import hmac
import hashlib
import secrets
import json
from flask import Flask, request, Response
import threading

# ==========================
# CONFIG / ENV
# ==========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SECRET_KEY = os.getenv("SECRET_KEY", "bHfJk82mDH7sks93haHD02mna293kdlZ").encode()

STORAGE_FILE = "scripts.json"

# ==========================
# STORAGE SYSTEM
# ==========================
def load_storage():
    if not os.path.exists(STORAGE_FILE):
        return {}
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_storage():
    with open(STORAGE_FILE, "w") as f:
        json.dump(script_storage, f, indent=2)

script_storage = load_storage()

# ==========================
# FLASK
# ==========================
app = Flask(__name__)

def get_base_url():
    """Auto-detect your Render domain."""
    return request.host_url.rstrip("/")

@app.route("/")
def home():
    return "✔ Script server is running!"

@app.route("/signed/<script_id>")
def signed(script_id):
    data = script_storage.get(script_id)
    if not data:
        return Response("Not Found", status=404)

    ts = str(int(time.time()))
    message = f"{script_id}{ts}".encode()
    sig = hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()

    base = get_base_url()
    raw_url = f"{base}/raw/{script_id}?token={data['token']}&ts={ts}&sig={sig}"

    return f'loadstring(game:HttpGet("{raw_url}"))()'

@app.route("/raw/<script_id>")
def raw(script_id):
    data = script_storage.get(script_id)
    if not data:
        return Response("Not Found", status=404)

    token = request.args.get("token")
    ts = request.args.get("ts")
    sig = request.args.get("sig")

    if not token or not ts or not sig:
        return Response("Missing parameters.", status=403)

    if token != data["token"]:
        return Response("Invalid token.", status=403)

    # Expiry (10 sec window)
    if abs(time.time() - int(ts)) > 10:
        return Response("Expired link.", status=403)

    # HMAC validation
    message = f"{script_id}{ts}".encode()
    expected_sig = hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig, sig):
        return Response("Invalid signature.", status=403)

    # Only roblox can fetch the raw script
    ua = (request.headers.get("User-Agent") or "").lower()
    if not ua.startswith("roblox"):
        return Response("what are you doing here go back to roblox.", status=403)

    return Response(data["content"], mimetype="text/plain")

# ==========================
# DISCORD BOT
# ==========================
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def generate_id():
    return secrets.token_hex(4)

@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("Commands synced.")
    except Exception as e:
        print("Sync error:", e)

@bot.tree.command(name="upload")
@app_commands.describe(file="Upload a .lua file")
async def upload(interaction: discord.Interaction, file: discord.Attachment):
    if not file.filename.endswith(".lua"):
        await interaction.response.send_message("❌ Only `.lua` allowed.", ephemeral=True)
        return

    content = (await file.read()).decode()
    script_id = generate_id()
    token = secrets.token_urlsafe(12)

    script_storage[script_id] = {
        "content": content,
        "token": token
    }
    save_storage()

    await interaction.response.send_message(
        f"📥 Uploaded! Script ID: `{script_id}`\nUse `/get {script_id}` to get loadstring.",
        ephemeral=True
    )

@bot.tree.command(name="get")
@app_commands.describe(script_id="ID from /upload")
async def get_script(interaction: discord.Interaction, script_id: str):
    if script_id not in script_storage:
        await interaction.response.send_message("❌ Script not found.", ephemeral=True)
        return

    base = "https://" + os.getenv("RENDER_EXTERNAL_URL", "")
    if not base or "None" in base:
        # fallback inside request
        base = "https://zero-trace-p1aq.onrender.com"

    signed = f"{base}/signed/{script_id}"
    code = f'loadstring(game:HttpGet("{signed}"))()'

    await interaction.response.send_message(
        f"🔐 Loadstring:\n```lua\n{code}\n```",
        ephemeral=True
    )

@bot.tree.command(name="list")
async def list_scripts(interaction: discord.Interaction):
    if not script_storage:
        await interaction.response.send_message("No scripts stored.", ephemeral=True)
        return

    msg = "\n".join(f"- `{k}`" for k in script_storage.keys())
    await interaction.response.send_message(msg, ephemeral=True)

# ==========================
# THREAD STARTERS
# ==========================
def start_discord():
    if not DISCORD_TOKEN:
        print("❌ Missing DISCORD_TOKEN in environment variables.")
        return
    bot.run(DISCORD_TOKEN)

def start_flask():
    # Render uses PORT env
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==========================
# MAIN
# ==========================
if __name__ == "__main__":
    threading.Thread(target=start_flask).start()
    threading.Thread(target=start_discord).start()


