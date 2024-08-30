from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

@app.route('/')
def index():
    conn = sqlite3.connect('file_uploads.db')
    c = conn.cursor()
    c.execute("SELECT * FROM settings")
    settings = c.fetchall()
    conn.close()
    return render_template('index.html', settings=settings)

@app.route('/update_settings', methods=['POST'])
def update_settings():
    channel_id = request.form['channel_id']
    role_name = request.form['role_name']
    max_uploads = request.form['max_uploads']

    conn = sqlite3.connect('file_uploads.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (channel_id, role_name, max_uploads) VALUES (?, ?, ?)",
              (channel_id, role_name, max_uploads))
    conn.commit()
    conn.close()

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))