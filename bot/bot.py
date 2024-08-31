import discord
from discord.ext import commands
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os
import io
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
        await user.send(content)
        print(f"Private message sent to {user.name}")
    except discord.errors.Forbidden:
        print(f"Unable to send DM to {user.name}. Sending in channel instead.")
        await channel.send(f"{user.mention} {content}", delete_after=10)
    except Exception as e:
        print(f"Unexpected error in send_private_message: {e}")
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
        await db.execute('''CREATE TABLE IF NOT EXISTS blocked_channels
                            (channel_id INTEGER PRIMARY KEY)''')
        await db.commit()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.attachments:
        channel_id = message.channel.id
        user_id = message.author.id
        username = message.author.name
        
        # Filter attachments to only count .mp3 and .wav files
        counted_attachments = [att for att in message.attachments if att.filename.lower().endswith(('.mp3', '.wav'))]
        if not counted_attachments:
            # If no counted attachments, process the message normally without updating upload count
            return await bot.process_commands(message)

        async with aiosqlite.connect('file_uploads.db') as db:
            # Check if the channel is in the blocked list
            async with db.execute("SELECT 1 FROM blocked_channels WHERE channel_id = ?", (channel_id,)) as cursor:
                is_blocked = await cursor.fetchone()

            if is_blocked:
                # If the channel is blocked, delete the message and notify the user
                try:
                    await message.delete()
                    await send_private_message(message.channel, message.author, 
                        f"Your message was deleted because .mp3/.wav uploads are not allowed in this channel.")
                    return
                except discord.errors.NotFound:
                    print(f"Message {message.id} was already deleted")
                except discord.errors.Forbidden:
                    print(f"Bot doesn't have permission to delete message {message.id}")
                    return

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
            else:
                current_uploads = 0
                await db.execute("INSERT INTO user_uploads (user_id, username, uploads, last_reset) VALUES (?, ?, 0, ?)", 
                                 (user_id, username, datetime.datetime.now().isoformat()))

            remaining_uploads = max_uploads - current_uploads
            attachments_count = len(counted_attachments)

            if remaining_uploads >= attachments_count:
                # All attachments allowed
                new_upload_count = current_uploads + attachments_count
                await db.execute("UPDATE user_uploads SET uploads = ?, username = ? WHERE user_id = ?", 
                                 (new_upload_count, username, user_id))
                await db.commit()
                print(f"Updated upload count for user {username}: {new_upload_count}")

                # await send_private_message(message.channel, message.author, 
                #     f"Your current .mp3/.wav upload count is now {new_upload_count}/{max_uploads}.")
            else:
                # Upload limit exceeded
                try:
                    await message.delete()
                    await send_private_message(message.channel, message.author, 
                        f"Your upload was deleted as it would exceed your daily limit. "
                        f"You have {remaining_uploads} uploads remaining out of {max_uploads}. ")
                except discord.errors.NotFound:
                    print(f"Message {message.id} was already deleted")
                except discord.errors.Forbidden:
                    print(f"Bot doesn't have permission to delete message {message.id}")
                    await message.channel.send(
                        f"{message.author.mention}, your upload exceeds your daily limit. "
                        f"You have {remaining_uploads} uploads remaining out of {max_uploads}. "
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
    async with aiosqlite.connect('file_uploads.db') as db:
        # Get user's current upload count
        async with db.execute("SELECT uploads FROM user_uploads WHERE user_id = ?", (user_id,)) as cursor:
            user_uploads = await cursor.fetchone()

    current_uploads = user_uploads[0] if user_uploads else 0
    await ctx.send(f"{ctx.author.mention}, you have used {current_uploads} uploads.")

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