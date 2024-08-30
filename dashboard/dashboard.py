from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

def get_db_connection():
    conn = sqlite3.connect('file_uploads.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return redirect(url_for('settings'))

@app.route('/settings')
def settings():
    conn = get_db_connection()
    settings = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    return render_template('settings.html', settings=settings, active_page='settings')

@app.route('/update_settings', methods=['POST'])
def update_settings():
    channel_id = request.form['channel_id']
    role_name = request.form['role_name']
    max_uploads = request.form['max_uploads']

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (channel_id, role_name, max_uploads) VALUES (?, ?, ?)",
                 (channel_id, role_name, max_uploads))
    conn.commit()
    conn.close()

    flash('Settings updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/users')
def users():
    conn = get_db_connection()
    users = conn.execute("SELECT user_id, username, uploads, last_reset FROM user_uploads").fetchall()
    conn.close()
    return render_template('users.html', users=users, active_page='users')

@app.route('/reset_user/<int:user_id>', methods=['POST'])
def reset_user(user_id):
    conn = get_db_connection()
    conn.execute("UPDATE user_uploads SET uploads = 0, last_reset = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    flash(f'User {user_id} has been reset.', 'success')
    return redirect(url_for('users'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))