import threading
from bot.bot import run_bot
from dashboard.dashboard import app

def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    flask_thread = threading.Thread(target=run_flask)

    bot_thread.start()
    flask_thread.start()

    bot_thread.join()
    flask_thread.join()