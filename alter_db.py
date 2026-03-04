import sqlite3

def alter_db():
    conn = sqlite3.connect('data/trading_bot.db')
    cursor = conn.cursor()

    try:
        cursor.execute('ALTER TABLE global_config ADD COLUMN max_exposure_percent FLOAT DEFAULT 10.0')
        print("Added max_exposure_percent")
    except sqlite3.OperationalError as e:
        print("max_exposure_percent might exist:", e)

    try:
        cursor.execute('ALTER TABLE global_config ADD COLUMN cooldown_minutes INTEGER DEFAULT 120')
        print("Added cooldown_minutes")
    except sqlite3.OperationalError as e:
        print("cooldown_minutes might exist:", e)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    alter_db()
