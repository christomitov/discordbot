import discord
from discord.ext import commands
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import pytz
import os
from dotenv import load_dotenv, find_dotenv

# Load environment variables (unchanged)
dotenv_path = find_dotenv(usecwd=True)
print(f".env file path: {dotenv_path}")

if not dotenv_path:
    print("Error: .env file not found!")
else:
    print("\nAttempting to load .env file:")
    load_result = load_dotenv(dotenv_path, override=True, verbose=True)

# Debug print (unchanged)
token = os.getenv('DISCORD_BOT_TOKEN')
if token:
    print(f"Token loaded (first 10 chars): {token[:10]}...")
    print(f"Token length: {len(token)}")
else:
    print("ERROR: No token found in environment variables")

# Bot setup (unchanged)
intents = discord.Intents.default()
intents.message_content = True
intents.guild_messages = True
intents.dm_messages = True
intents.guild_reactions = True
intents.dm_reactions = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Scheduler setup
scheduler = AsyncIOScheduler()

async def reset_uploads():
    try:
        est = pytz.timezone('US/Eastern')
        current_time_est = datetime.datetime.now(est)
        is_sunday_midnight = current_time_est.weekday() == 6 and current_time_est.hour == 0 and current_time_est.minute < 5

        current_time = datetime.datetime.now().isoformat()
        async with aiosqlite.connect('file_uploads.db') as db:
            # Reset daily channels
            cursor = await db.execute("""
                UPDATE user_channel_uploads
                SET uploads = 0,
                    last_reset = ?
                WHERE channel_id IN (
                    SELECT channel_id FROM channel_settings
                    WHERE reset_frequency = 'daily'
                )
                AND datetime(last_reset) < datetime('now', '-1 day')
            """, (current_time,))
            daily_rows_affected = cursor.rowcount

            # Reset weekly channels on Sunday at midnight EST
            if is_sunday_midnight:
                cursor = await db.execute("""
                    UPDATE user_channel_uploads
                    SET uploads = 0,
                        last_reset = ?
                    WHERE channel_id IN (
                        SELECT channel_id FROM channel_settings
                        WHERE reset_frequency = 'weekly'
                    )
                """, (current_time_est.isoformat(),))
                weekly_rows_affected = cursor.rowcount
            else:
                weekly_rows_affected = 0

            await db.commit()
        print(f"Daily upload counts reset at {current_time}. Daily rows affected: {daily_rows_affected}, Weekly rows affected: {weekly_rows_affected}")
    except Exception as e:
        print(f"Error in reset_uploads: {e}")

async def send_private_message(channel, user, content):
    try:
        await user.send(content)
        print(f"Private message sent to {user.name}")
    except discord.errors.Forbidden:
        print(f"Unable to send DM to {user.name}. Sending in channel instead.")
        await channel.send(f"{user.mention} {content}", delete_after=10)
    except Exception as e:
        print(f"Unexpected error in send_private_message: {e}")
        await channel.send(f"{user.mention} {content}", delete_after=10)

async def update_channel_names():
    async with aiosqlite.connect('file_uploads.db') as db:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                await db.execute("""
                    INSERT OR REPLACE INTO channel_names (channel_id, channel_name)
                    VALUES (?, ?)
                """, (channel.id, channel.name))
        await db.commit()
    print("Channel names updated.")

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_channel_uploads
                            (user_id INTEGER,
                             channel_id INTEGER,
                             username TEXT,
                             uploads INTEGER,
                             last_reset TEXT,
                             PRIMARY KEY (user_id, channel_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             channel_id INTEGER,
                             role_name TEXT,
                             max_uploads INTEGER,
                             order_index INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS global_settings
                            (id INTEGER PRIMARY KEY CHECK (id = 1),
                             default_max_uploads INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS blocked_channels
                            (channel_id INTEGER PRIMARY KEY)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channel_names
                            (channel_id INTEGER PRIMARY KEY,
                             channel_name TEXT)''')
        # Check if reset_frequency column exists in channel_settings table
        cursor = await db.execute("PRAGMA table_info(channel_settings)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        if 'reset_frequency' not in column_names:
            # Add reset_frequency column if it doesn't exist
            await db.execute('''ALTER TABLE channel_settings
                                ADD COLUMN reset_frequency TEXT DEFAULT 'daily' ''')
            print("Added reset_frequency column to channel_settings table")
        else:
            print("reset_frequency column already exists in channel_settings table")

        await db.commit()

    # Update channel names immediately
    await update_channel_names()

    # Reset uploads on launch
    await reset_uploads()

    # Start the scheduler
    scheduler.start()
    print("Scheduler started")

    # Schedule jobs after starting the scheduler
    scheduler.add_job(reset_uploads, CronTrigger(minute='*/5'))
    scheduler.add_job(update_channel_names, CronTrigger(hour='*/6'))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.attachments:
        channel_id = message.channel.id
        user_id = message.author.id
        username = message.author.name

        counted_attachments = [att for att in message.attachments if att.filename.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg'))]
        if not counted_attachments:
            return await bot.process_commands(message)

        async with aiosqlite.connect('file_uploads.db') as db:
            # Check if the channel is blocked
            async with db.execute("SELECT 1 FROM blocked_channels WHERE channel_id = ?", (channel_id,)) as cursor:
                is_blocked = await cursor.fetchone()

            if is_blocked:
                try:
                    await message.delete()
                    await send_private_message(message.channel, message.author,
                        f"Your message was deleted because audio uploads are not allowed in this channel.")
                    return
                except discord.errors.NotFound:
                    print(f"Message {message.id} was already deleted")
                except discord.errors.Forbidden:
                    print(f"Bot doesn't have permission to delete message {message.id}")
                    return

            # Get channel settings
            async with db.execute("SELECT role_name, max_uploads, reset_frequency FROM channel_settings WHERE channel_id = ? ORDER BY order_index", (channel_id,)) as cursor:
                channel_settings = await cursor.fetchall()

            # Get global settings
            async with db.execute("SELECT default_max_uploads FROM global_settings WHERE id = 1") as cursor:
                global_settings = await cursor.fetchone()

            # Get user's roles
            user_roles = [role.name for role in message.author.roles]

            # Determine max_uploads and reset_frequency based on user's highest priority role
            max_uploads = None
            reset_frequency = 'daily'  # Default to daily if not set
            for role_name, role_max_uploads, role_reset_frequency in channel_settings:
                if role_name in user_roles:
                    max_uploads = role_max_uploads
                    reset_frequency = role_reset_frequency
                    break  # Break after finding the highest priority role the user has

            if max_uploads is None:
                if global_settings:
                    max_uploads = global_settings[0]
                else:
                    # No settings found, allow unlimited uploads
                    return

            # Check user's current upload count
            async with db.execute("SELECT uploads, last_reset FROM user_channel_uploads WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)) as cursor:
                user_data = await cursor.fetchone()

            current_time = datetime.datetime.now(pytz.utc)
            if user_data:
                current_uploads, last_reset = user_data
                last_reset = pytz.utc.localize(datetime.datetime.fromisoformat(last_reset))
                if reset_frequency == 'daily' and (current_time - last_reset) > datetime.timedelta(days=1):
                    current_uploads = 0
                elif reset_frequency == 'weekly' and (current_time - last_reset) > datetime.timedelta(days=7):
                    current_uploads = 0
            else:
                current_uploads = 0

            remaining_uploads = max_uploads - current_uploads
            attachments_count = len(counted_attachments)

            if remaining_uploads >= attachments_count:
                # All attachments allowed
                new_upload_count = current_uploads + attachments_count
                await db.execute("INSERT OR REPLACE INTO user_channel_uploads (user_id, channel_id, username, uploads, last_reset) VALUES (?, ?, ?, ?, ?)",
                                 (user_id, channel_id, username, new_upload_count, current_time.isoformat()))
                await db.commit()
                print(f"Updated upload count for user {username} in channel {channel_id}: {new_upload_count}")
            else:
                # Upload limit exceeded
                try:
                    await message.delete()
                    await send_private_message(message.channel, message.author,
                        f"Your upload was deleted as it would exceed your {reset_frequency} limit for this channel. "
                        f"You have {remaining_uploads} uploads remaining out of {max_uploads} in this channel.")
                except discord.errors.NotFound:
                    print(f"Message {message.id} was already deleted")
                except discord.errors.Forbidden:
                    print(f"Bot doesn't have permission to delete message {message.id}")
                    await message.channel.send(
                        f"{message.author.mention}, your upload exceeds your {reset_frequency} limit for this channel. "
                        f"You have {remaining_uploads} uploads remaining out of {max_uploads} in this channel. "
                        f"Please delete this message and upload fewer files.")

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def set_channel_settings(ctx, channel_id: int, role_name: str, max_uploads: int, order_index: int):
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("INSERT OR REPLACE INTO channel_settings (channel_id, role_name, max_uploads, order_index) VALUES (?, ?, ?, ?)",
                         (channel_id, role_name, max_uploads, order_index))
        await db.commit()
    await ctx.send(f"Channel settings updated for channel {channel_id}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_global_limit(ctx, max_uploads: int):
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("INSERT OR REPLACE INTO global_settings (id, default_max_uploads) VALUES (1, ?)", (max_uploads,))
        await db.commit()
    await ctx.send(f"Global upload limit set to {max_uploads}")

@bot.command()
async def check_uploads(ctx):
    user_id = ctx.author.id
    channel_id = ctx.channel.id
    async with aiosqlite.connect('file_uploads.db') as db:
        async with db.execute("SELECT uploads FROM user_channel_uploads WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)) as cursor:
            user_uploads = await cursor.fetchone()

    current_uploads = user_uploads[0] if user_uploads else 0
    await ctx.send(f"{ctx.author.mention}, you have used {current_uploads} uploads in this channel.")

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
