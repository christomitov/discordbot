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
    channel_settings = conn.execute("SELECT * FROM channel_settings").fetchall()
    role_hierarchy = conn.execute("SELECT * FROM role_hierarchy").fetchall()
    global_settings = conn.execute("SELECT default_max_uploads FROM global_settings WHERE id = 1").fetchone()
    conn.close()
    return render_template('settings.html', channel_settings=channel_settings, role_hierarchy=role_hierarchy, global_settings=global_settings, active_page='settings')

@app.route('/update_global_settings', methods=['POST'])
def update_global_settings():
    default_max_uploads = request.form['default_max_uploads']

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO global_settings (id, default_max_uploads) VALUES (1, ?)",
                 (default_max_uploads,))
    conn.commit()
    conn.close()

    flash('Global settings updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/update_channel_settings', methods=['POST'])
def update_channel_settings():
    channel_id = request.form['channel_id']
    role_name = request.form['role_name']
    max_uploads = request.form['max_uploads']

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO channel_settings (channel_id, role_name, max_uploads) VALUES (?, ?, ?)",
                 (channel_id, role_name, max_uploads))
    conn.commit()
    conn.close()

    flash('Channel settings updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/delete_channel_settings/<int:channel_id>', methods=['POST'])
def delete_channel_settings(channel_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM channel_settings WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()

    flash('Channel settings deleted successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/update_role_hierarchy', methods=['POST'])
def update_role_hierarchy():
    role_name = request.form['role_name']
    level = request.form['level']

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO role_hierarchy (role_name, level) VALUES (?, ?)",
                 (role_name, level))
    conn.commit()
    conn.close()

    flash('Role hierarchy updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/delete_role_hierarchy/<string:role_name>', methods=['POST'])
def delete_role_hierarchy(role_name):
    conn = get_db_connection()
    conn.execute("DELETE FROM role_hierarchy WHERE role_name = ?", (role_name,))
    conn.commit()
    conn.close()

    flash('Role hierarchy entry deleted successfully!', 'success')
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