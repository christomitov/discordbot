import sys
import logging
from dashboard.dashboard import app
from bot.bot import run_bot
import threading

logging.basicConfig(level=logging.DEBUG, filename='/home/botuser/discordbot/app.log', filemode='a',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def run_flask():
    app.run()

def run_app():
    try:
        bot_thread = threading.Thread(target=run_bot)
        flask_thread = threading.Thread(target=run_flask)
        bot_thread.start()
        flask_thread.start()
        bot_thread.join()
        flask_thread.join()
    except Exception as e:
        logging.error(f"Error in run_app: {str(e)}", exc_info=True)
        sys.exit(1)

# This is the line Gunicorn is looking for
application = app

if __name__ == "__main__":
    run_app()
