import discord
from discord.ext import commands
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os
from dotenv import load_dotenv, find_dotenv

# Load environment variables
dotenv_path = find_dotenv(usecwd=True)
print(f".env file path: {dotenv_path}")

if not dotenv_path:
    print("Error: .env file not found!")
else:
    print("\nAttempting to load .env file:")
    load_result = load_dotenv(dotenv_path, override=True, verbose=True)

# Debug print
token = os.getenv('DISCORD_BOT_TOKEN')
if token:
    print(f"Token loaded (first 10 chars): {token[:10]}...")
    print(f"Token length: {len(token)}")
else:
    print("ERROR: No token found in environment variables")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Scheduler setup
scheduler = AsyncIOScheduler()

async def reset_uploads():
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("UPDATE user_uploads SET uploads = 0, last_reset = ?", (datetime.datetime.now().isoformat(),))
        await db.commit()
    print("Daily upload counts reset.")

scheduler.add_job(reset_uploads, CronTrigger(hour=0, minute=0))
scheduler.start()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_uploads
                            (user_id INTEGER PRIMARY KEY, username TEXT, uploads INTEGER, last_reset TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                            (channel_id INTEGER PRIMARY KEY, role_name TEXT, max_uploads INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS role_hierarchy
                            (role_name TEXT PRIMARY KEY, level INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS global_settings
                            (id INTEGER PRIMARY KEY CHECK (id = 1), default_max_uploads INTEGER)''')
        await db.commit()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.attachments:
        channel_id = message.channel.id
        user_id = message.author.id
        username = message.author.name

        async with aiosqlite.connect('file_uploads.db') as db:
            async with db.execute("SELECT role_name, max_uploads FROM channel_settings WHERE channel_id = ?", (channel_id,)) as cursor:
                channel_settings = await cursor.fetchone()

            if not channel_settings:
                async with db.execute("SELECT default_max_uploads FROM global_settings WHERE id = 1") as cursor:
                    global_settings = await cursor.fetchone()
                if global_settings:
                    max_uploads = global_settings[0]
                    required_role_name = None  # No specific role required for global limit
                else:
                    return  # No global setting, allow unlimited uploads

            else:
                required_role_name, max_uploads = channel_settings

            if required_role_name:
                user_roles = [role.name for role in message.author.roles]
                async with db.execute("SELECT MAX(level) FROM role_hierarchy WHERE role_name IN ({})".format(','.join('?' * len(user_roles))), user_roles) as cursor:
                    user_highest_level = await cursor.fetchone()

                async with db.execute("SELECT level FROM role_hierarchy WHERE role_name = ?", (required_role_name,)) as cursor:
                    required_level = await cursor.fetchone()

                if not user_highest_level or not required_level or user_highest_level[0] < required_level[0]:
                    await message.delete()
                    try:
                        await message.author.send(f"You don't have the required role level to upload files in that channel.")
                    except discord.errors.Forbidden:
                        print(f"Unable to send DM to user {message.author.name}")
                    return

            # Check user's upload count
            async with db.execute("SELECT uploads FROM user_uploads WHERE user_id = ?", (user_id,)) as cursor:
                user_uploads = await cursor.fetchone()

            if user_uploads:
                current_uploads = user_uploads[0]
                await db.execute("UPDATE user_uploads SET username = ? WHERE user_id = ?", (username, user_id))
            else:
                current_uploads = 0
                await db.execute("INSERT INTO user_uploads (user_id, username, uploads, last_reset) VALUES (?, ?, 0, ?)", 
                                 (user_id, username, datetime.datetime.now().isoformat()))

            new_upload_count = current_uploads + len(message.attachments)

            if new_upload_count > max_uploads:
                await message.delete()
                if current_uploads <= max_uploads:
                    try:
                        await message.author.send(f"You've reached your daily upload limit in the channel.")
                    except discord.errors.Forbidden:
                        print(f"Unable to send DM to user {message.author.name}")
            else:
                await db.execute("UPDATE user_uploads SET uploads = ? WHERE user_id = ?", (new_upload_count, user_id))

            await db.commit()

    await bot.process_commands(message)
    
@bot.command()
@commands.has_permissions(administrator=True)
async def set_channel_settings(ctx, channel_id: int, role_name: str, max_uploads: int):
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("INSERT OR REPLACE INTO channel_settings (channel_id, role_name, max_uploads) VALUES (?, ?, ?)",
                         (channel_id, role_name, max_uploads))
        await db.commit()
    await ctx.send(f"Channel settings updated for channel {channel_id}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_role_level(ctx, role_name: str, level: int):
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("INSERT OR REPLACE INTO role_hierarchy (role_name, level) VALUES (?, ?)",
                         (role_name, level))
        await db.commit()
    await ctx.send(f"Role hierarchy updated for role {role_name}")


def run_bot():
    token = os.getenv('DISCORD_BOT_TOKEN')

    if not token:
        print("ERROR: DISCORD_BOT_TOKEN not found in environment variables.")
        return
    try:
        bot.run(token)
    except discord.errors.LoginFailure as e:
        print(f"ERROR: Failed to log in: {e}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")

if __name__ == "__main__":
    run_bot()