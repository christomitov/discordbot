from dashboard import app as application
from bot import bot, run_bot
import threading

def run_flask():
    application.run()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    flask_thread = threading.Thread(target=run_flask)

    bot_thread.start()
    flask_thread.start()

    bot_thread.join()
    flask_thread.join()
