from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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
    return redirect(url_for('channels'))

@app.route('/channels')
def channels():
    conn = get_db_connection()
    channels = conn.execute("""
        SELECT cn.channel_id, cn.channel_name, 
               COUNT(DISTINCT cs.role_name) as role_count,
               CASE WHEN bc.channel_id IS NOT NULL THEN 1 ELSE 0 END as is_blocked
        FROM channel_names cn
        LEFT JOIN channel_settings cs ON cn.channel_id = cs.channel_id
        LEFT JOIN blocked_channels bc ON cn.channel_id = bc.channel_id
        GROUP BY cn.channel_id
        ORDER BY cn.channel_name
    """).fetchall()
    conn.close()
    return render_template('channels.html', channels=channels, active_page='channels')

@app.route('/channel/<int:channel_id>')
def channel_settings(channel_id):
    conn = get_db_connection()
    channel = conn.execute("SELECT * FROM channel_names WHERE channel_id = ?", (channel_id,)).fetchone()
    settings = conn.execute("SELECT * FROM channel_settings WHERE channel_id = ? ORDER BY order_index", (channel_id,)).fetchall()
    is_blocked = conn.execute("SELECT 1 FROM blocked_channels WHERE channel_id = ?", (channel_id,)).fetchone() is not None
    conn.close()
    return render_template('channel_settings.html', channel=channel, settings=settings, is_blocked=is_blocked, active_page='channels')

@app.route('/update_channel_settings/<int:channel_id>', methods=['POST'])
def update_channel_settings(channel_id):
    role_name = request.form['role_name']
    max_uploads = request.form['max_uploads']

    conn = get_db_connection()
    max_order = conn.execute("SELECT MAX(order_index) FROM channel_settings WHERE channel_id = ?", (channel_id,)).fetchone()[0]
    new_order = (max_order or 0) + 1
    conn.execute("INSERT INTO channel_settings (channel_id, role_name, max_uploads, order_index) VALUES (?, ?, ?, ?)",
                 (channel_id, role_name, max_uploads, new_order))
    conn.commit()
    conn.close()

    flash('Channel settings updated successfully!', 'success')
    return redirect(url_for('channel_settings', channel_id=channel_id))

@app.route('/reorder_channel_settings/<int:channel_id>', methods=['POST'])
def reorder_channel_settings(channel_id):
    new_order = request.json['new_order']
    conn = get_db_connection()
    for index, setting_id in enumerate(new_order):
        conn.execute("UPDATE channel_settings SET order_index = ? WHERE id = ? AND channel_id = ?", (index, setting_id, channel_id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/delete_channel_settings/<int:channel_id>/<int:setting_id>', methods=['POST'])
def delete_channel_settings(channel_id, setting_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM channel_settings WHERE id = ? AND channel_id = ?", (setting_id, channel_id))
    conn.commit()
    conn.close()

    flash('Channel setting deleted successfully!', 'success')
    return redirect(url_for('channel_settings', channel_id=channel_id))

@app.route('/toggle_channel_block/<int:channel_id>', methods=['POST'])
def toggle_channel_block(channel_id):
    conn = get_db_connection()
    is_blocked = conn.execute("SELECT 1 FROM blocked_channels WHERE channel_id = ?", (channel_id,)).fetchone() is not None
    
    if is_blocked:
        conn.execute("DELETE FROM blocked_channels WHERE channel_id = ?", (channel_id,))
        flash('Channel unblocked successfully!', 'success')
    else:
        conn.execute("INSERT INTO blocked_channels (channel_id) VALUES (?)", (channel_id,))
        flash('Channel blocked successfully!', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('channel_settings', channel_id=channel_id))

@app.route('/update_global_settings', methods=['POST'])
def update_global_settings():
    default_max_uploads = request.form['default_max_uploads']

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO global_settings (id, default_max_uploads) VALUES (1, ?)",
                 (default_max_uploads,))
    conn.commit()
    conn.close()

    flash('Global settings updated successfully!', 'success')
    return redirect(url_for('channels'))

@app.route('/users')
def users():
    conn = get_db_connection()
    users = conn.execute("""
        SELECT u.user_id, u.username, u.channel_id, u.uploads, u.last_reset, 
               COALESCE(cn.channel_name, 'Unknown Channel') as channel_name
        FROM user_channel_uploads u
        LEFT JOIN channel_names cn ON u.channel_id = cn.channel_id
        ORDER BY u.user_id, u.channel_id
    """).fetchall()
    conn.close()
    return render_template('users.html', users=users, active_page='users')

@app.route('/reset_user/<int:user_id>/<int:channel_id>', methods=['POST'])
def reset_user(user_id, channel_id):
    conn = get_db_connection()
    conn.execute("""
        UPDATE user_channel_uploads 
        SET uploads = 0, last_reset = CURRENT_TIMESTAMP 
        WHERE user_id = ? AND channel_id = ?
    """, (user_id, channel_id))
    conn.commit()
    conn.close()
    
    flash(f'User {user_id} has been reset for channel {channel_id}.', 'success')
    return redirect(url_for('users'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))