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
intents.message_content = True
intents.guild_messages = True
intents.dm_messages = True
intents.guild_reactions = True
intents.dm_reactions = True
intents.guilds = True
intents.members = True  # This might require special approval from Discord
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

async def send_private_message(channel, user, content):
    try:
        # Attempt to send a direct message to the user
        await user.send(content)
        print(f"Private message sent to {user.name}")
    except discord.errors.Forbidden:
        print(f"Unable to send DM to {user.name}. Sending in channel instead.")
        # If DM fails, send a message in the channel that only the user can see
        await channel.send(f"{user.mention} {content}", delete_after=10)
    except Exception as e:
        print(f"Unexpected error in send_private_message: {e}")
        # Fallback to regular channel message
        await channel.send(f"{user.mention} {content}", delete_after=10)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_uploads
                            (user_id INTEGER PRIMARY KEY, username TEXT, uploads INTEGER, last_reset TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             channel_id INTEGER,
                             role_name TEXT,
                             max_uploads INTEGER,
                             order_index INTEGER)''')
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
            # Get all channel settings ordered by priority
            async with db.execute("SELECT channel_id, role_name, max_uploads FROM channel_settings ORDER BY order_index") as cursor:
                all_channel_settings = await cursor.fetchall()

            # Get global settings
            async with db.execute("SELECT default_max_uploads FROM global_settings WHERE id = 1") as cursor:
                global_settings = await cursor.fetchone()

            # Get user's roles
            user_roles = [role.name for role in message.author.roles]

            # Determine max_uploads based on user's highest role across all channels
            max_uploads = None
            for channel_id_setting, role_name, role_max_uploads in all_channel_settings:
                if role_name in user_roles:
                    max_uploads = role_max_uploads
                    break  # Break after finding the highest role the user has

            if max_uploads is None:
                if global_settings:
                    max_uploads = global_settings[0]
                else:
                    # No settings found, allow unlimited uploads
                    return

            # Check user's current upload count
            async with db.execute("SELECT uploads FROM user_uploads WHERE user_id = ?", (user_id,)) as cursor:
                user_uploads = await cursor.fetchone()

            if user_uploads:
                current_uploads = user_uploads[0]
                await db.execute("UPDATE user_uploads SET username = ? WHERE user_id = ?", (username, user_id))
            else:
                current_uploads = 0
                await db.execute("INSERT INTO user_uploads (user_id, username, uploads, last_reset) VALUES (?, ?, 0, ?)", 
                                 (user_id, username, datetime.datetime.now().isoformat()))

            remaining_uploads = max_uploads - current_uploads
            allowed_attachments = min(remaining_uploads, len(message.attachments))

            if allowed_attachments > 0:
                if allowed_attachments < len(message.attachments):
                    # Partial upload
                    new_message = await message.channel.send(content=message.content, 
                                                             files=message.attachments[:allowed_attachments])
                    await send_private_message(message.channel, message.author, 
                        f"{message.author.mention}, only {allowed_attachments} of your {len(message.attachments)} uploads were allowed due to daily limit.")
                    await message.delete()
                else:
                    # All attachments allowed
                    new_message = message

                new_upload_count = current_uploads + allowed_attachments
                await db.execute("UPDATE user_uploads SET uploads = ? WHERE user_id = ?", (new_upload_count, user_id))
                await db.commit()
            else:
                # No uploads allowed
                await send_private_message(message.channel, message.author, 
                    f"{message.author.mention}, you've reached your daily upload limit across all channels.")
                await message.delete()

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