import discord
from discord.ext import commands
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database setup
conn = sqlite3.connect('file_uploads.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS user_uploads
             (user_id INTEGER PRIMARY KEY, uploads INTEGER, last_reset TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS settings
             (channel_id INTEGER PRIMARY KEY, role_name TEXT, max_uploads INTEGER)''')

conn.commit()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Scheduler setup
scheduler = AsyncIOScheduler()

async def reset_uploads():
    c.execute("UPDATE user_uploads SET uploads = 0, last_reset = ?", (datetime.datetime.now().isoformat(),))
    conn.commit()
    print("Daily upload counts reset.")

scheduler.add_job(reset_uploads, CronTrigger(hour=0, minute=0))
scheduler.start()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Check if message has attachments
    if message.attachments:
        channel_id = message.channel.id
        user_id = message.author.id

        # Get channel settings
        c.execute("SELECT role_name, max_uploads FROM settings WHERE channel_id = ?", (channel_id,))
        channel_settings = c.fetchone()

        if not channel_settings:
            return  # Channel not configured

        required_role_name, max_uploads = channel_settings

        # Check user's role
        user_roles = [role.name for role in message.author.roles]
        if required_role_name not in user_roles:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, you don't have the required role ({required_role_name}) to upload files in this channel.")
            return

        # Check user's upload count
        c.execute("SELECT uploads FROM user_uploads WHERE user_id = ?", (user_id,))
        user_uploads = c.fetchone()

        if user_uploads:
            current_uploads = user_uploads[0]
        else:
            current_uploads = 0
            c.execute("INSERT INTO user_uploads (user_id, uploads, last_reset) VALUES (?, 0, ?)", 
                      (user_id, datetime.datetime.now().isoformat()))

        new_upload_count = current_uploads + len(message.attachments)

        if new_upload_count > max_uploads:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, you've reached your daily upload limit.")
        else:
            c.execute("UPDATE user_uploads SET uploads = ? WHERE user_id = ?", (new_upload_count, user_id))

        conn.commit()

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def set_channel_settings(ctx, channel_id: int, role_name: str, max_uploads: int):
    c.execute("INSERT OR REPLACE INTO settings (channel_id, role_name, max_uploads) VALUES (?, ?, ?)",
              (channel_id, role_name, max_uploads))
    conn.commit()
    await ctx.send(f"Channel settings updated for channel {channel_id}")

if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))