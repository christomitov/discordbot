import discord
from discord.ext import commands
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import pytz
import os
from dotenv import load_dotenv, find_dotenv
import logging
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        current_time = current_time_est.isoformat()
        
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
                AND datetime(last_reset) < datetime(?, '-1 day')
            """, (current_time, current_time))
            daily_rows_affected = cursor.rowcount

            # Reset weekly channels - check if it's been a week since last reset
            cursor = await db.execute("""
                UPDATE user_channel_uploads
                SET uploads = 0,
                    last_reset = ?
                WHERE channel_id IN (
                    SELECT channel_id FROM channel_settings
                    WHERE reset_frequency = 'weekly'
                )
                AND (
                    datetime(last_reset) < datetime(?, '-7 days')
                    OR (
                        ? = '0' -- Sunday
                        AND substr(?, 12, 2) = '00' -- Midnight hour
                        AND datetime(last_reset) < datetime(?, '-6 days')
                    )
                )
            """, (current_time, current_time, str(current_time_est.weekday()), current_time, current_time))
            weekly_rows_affected = cursor.rowcount

            await db.commit()
            
        logging.info(
            f"Upload counts reset at {current_time} EST. "
            f"Daily rows affected: {daily_rows_affected}, "
            f"Weekly rows affected: {weekly_rows_affected}"
        )
    except Exception as e:
        logging.error(f"Error in reset_uploads: {str(e)}")
        raise

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
        # First, add channel_type column if it doesn't exist
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channel_names
            (channel_id INTEGER PRIMARY KEY,
             channel_name TEXT,
             channel_type TEXT)
        """)
        
        for guild in bot.guilds:
            # Get both text channels and forum channels
            channels = guild.text_channels + guild.forums
            for channel in channels:
                channel_type = 'forum' if isinstance(channel, discord.ForumChannel) else 'text'
                await db.execute("""
                    INSERT OR REPLACE INTO channel_names (channel_id, channel_name, channel_type)
                    VALUES (?, ?, ?)
                """, (channel.id, channel.name, channel_type))
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
                             order_index INTEGER,
                             reset_frequency TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS global_settings
                            (id INTEGER PRIMARY KEY CHECK (id = 1),
                             default_max_uploads INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS blocked_channels
                            (channel_id INTEGER PRIMARY KEY)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channel_names
                            (channel_id INTEGER PRIMARY KEY,
                             channel_name TEXT,
                             channel_type TEXT)''')
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

        # Add channel_type column to channel_names if it doesn't exist
        cursor = await db.execute("PRAGMA table_info(channel_names)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'channel_type' not in column_names:
            await db.execute('''ALTER TABLE channel_names
                               ADD COLUMN channel_type TEXT DEFAULT 'text' ''')
            print("Added channel_type column to channel_names table")
        
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

    # Check if the channel is either a text channel or a forum thread
    if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
        return await bot.process_commands(message)

    if message.attachments:
        # For forum threads, get the parent channel ID
        channel_id = message.channel.parent_id if isinstance(message.channel, discord.Thread) else message.channel.id
        logging.info(f"Processing upload - Channel type: {type(message.channel)}, Channel ID: {channel_id}")
        
        user_id = message.author.id
        username = message.author.name

        counted_attachments = [att for att in message.attachments if att.filename.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg'))]
        if not counted_attachments:
            logging.info("No audio attachments found, skipping")
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
                except Exception as e:
                    print(f"Unexpected error in on_message: {e}")
                return

            # Get channel settings
            async with db.execute("SELECT role_name, max_uploads, reset_frequency FROM channel_settings WHERE channel_id = ? ORDER BY order_index", (channel_id,)) as cursor:
                channel_settings = await cursor.fetchall()
                logging.info(f"Found channel settings: {channel_settings}")

            # If no channel settings exist, allow unlimited uploads
            if not channel_settings:
                logging.info(f"No role limits set for channel {channel_id}, allowing unlimited uploads")
                return await bot.process_commands(message)

            # Get user's roles
            user_roles = [role.name for role in message.author.roles]
            logging.info(f"User roles: {user_roles}")

            # Determine max_uploads and reset_frequency based on user's highest priority role
            max_uploads = None
            reset_frequency = 'daily'  # Default to daily if not set
            for role_name, role_max_uploads, role_reset_frequency in channel_settings:
                if role_name in user_roles:
                    max_uploads = role_max_uploads
                    reset_frequency = role_reset_frequency
                    break  # Break after finding the highest priority role the user has

            if max_uploads is None:  # User has none of the configured roles but roles are required
                try:
                    await message.delete()
                    await send_private_message(message.channel, message.author,
                        "Your upload was deleted because you don't have the required role to upload in this channel.")
                    return
                except discord.errors.NotFound:
                    logging.info(f"Message {message.id} was already deleted")
                except discord.errors.Forbidden:
                    logging.info(f"Bot doesn't have permission to delete message {message.id}")
                return

            # Get user's current upload count
            async with db.execute("SELECT uploads, last_reset FROM user_channel_uploads WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)) as cursor:
                user_data = await cursor.fetchone()
                logging.info(f"Current user data: {user_data}")

            if user_data is None:
                # Create initial entry for new user with 0 uploads
                est = pytz.timezone('US/Eastern')
                current_time = datetime.datetime.now(est)
                await db.execute(
                    "INSERT INTO user_channel_uploads (user_id, channel_id, username, uploads, last_reset) VALUES (?, ?, ?, 0, ?)",
                    (user_id, channel_id, username, current_time.isoformat())
                )
                await db.commit()
                user_data = (0, current_time.isoformat())
                logging.info(f"Created initial entry for user {username} in channel {channel_id}")

            current_uploads = user_data[0] if user_data else 0
            logging.info(f"Current uploads: {current_uploads}, Attachments to add: {len(counted_attachments)}")

            remaining_uploads = max_uploads - current_uploads

            if remaining_uploads >= len(counted_attachments):
                # All attachments allowed
                new_upload_count = current_uploads + len(counted_attachments)
                if new_upload_count > max_uploads:
                    try:
                        await message.delete()
                        await send_private_message(message.channel, message.author,
                            f"Your upload was deleted as it would exceed your {reset_frequency} limit for this channel. "
                            f"You have {remaining_uploads} uploads remaining out of {max_uploads} in this channel.")
                        return
                    except discord.errors.NotFound:
                        print(f"Message {message.id} was already deleted")
                    except discord.errors.Forbidden:
                        print(f"Bot doesn't have permission to delete message {message.id}")
                    except Exception as e:
                        print(f"Unexpected error in on_message: {e}")
                    return
                
                est = pytz.timezone('US/Eastern')
                current_time = datetime.datetime.now(est)
                await db.execute("INSERT OR REPLACE INTO user_channel_uploads (user_id, channel_id, username, uploads, last_reset) VALUES (?, ?, ?, ?, ?)",
                                 (user_id, channel_id, username, new_upload_count, current_time.isoformat()))
                await db.commit()
                logging.info(f"Updated upload count for user {username} in channel {channel_id}: {new_upload_count}")
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
                return  # Stop processing this message

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def set_channel_settings(ctx, channel_id: int, role_name: str, max_uploads: int, order_index: int, reset_frequency: str = 'daily'):
    if reset_frequency not in ['daily', 'weekly']:
        await ctx.send("Error: reset_frequency must be either 'daily' or 'weekly'")
        return
        
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("""
            INSERT OR REPLACE INTO channel_settings 
            (channel_id, role_name, max_uploads, order_index, reset_frequency) 
            VALUES (?, ?, ?, ?, ?)
        """, (channel_id, role_name, max_uploads, order_index, reset_frequency))
        await db.commit()
    await ctx.send(f"Channel settings updated for channel {channel_id} with {reset_frequency} reset")

@bot.command()
async def check_uploads(ctx):
    # For forum threads, get the parent channel ID
    channel_id = ctx.channel.parent_id if isinstance(ctx.channel, discord.Thread) else ctx.channel.id
    user_id = ctx.author.id
    
    async with aiosqlite.connect('file_uploads.db') as db:
        # Check if channel has role limits
        async with db.execute("SELECT 1 FROM channel_settings WHERE channel_id = ?", (channel_id,)) as cursor:
            has_role_limits = await cursor.fetchone() is not None
            
        if not has_role_limits:
            await ctx.send(f"{ctx.author.mention}, this channel has no upload limits!")
            return
            
        async with db.execute("""
            SELECT u.uploads, cs.max_uploads, cs.reset_frequency 
            FROM user_channel_uploads u 
            LEFT JOIN channel_settings cs ON cs.channel_id = u.channel_id 
            WHERE u.user_id = ? AND u.channel_id = ? AND cs.role_name IN (
                SELECT name FROM json_each(?)
            )
            ORDER BY cs.order_index 
            LIMIT 1
        """, (user_id, channel_id, json.dumps([role.name for role in ctx.author.roles]))) as cursor:
            result = await cursor.fetchone()
            
        if result:
            current_uploads, max_uploads, reset_frequency = result
            await ctx.send(
                f"{ctx.author.mention}, you have used {current_uploads} out of {max_uploads} uploads "
                f"in this channel ({reset_frequency} reset)"
            )
        else:
            await ctx.send(
                f"{ctx.author.mention}, you don't have any roles with upload permissions in this channel"
            )

@bot.command()
@commands.has_permissions(administrator=True)
async def set_global_limit(ctx, max_uploads: int):
    async with aiosqlite.connect('file_uploads.db') as db:
        await db.execute("INSERT OR REPLACE INTO global_settings (id, default_max_uploads) VALUES (1, ?)", (max_uploads,))
        await db.commit()
    await ctx.send(f"Global upload limit set to {max_uploads}")

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
