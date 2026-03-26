import sqlite3

def alter_db():
    """Agrega columnas de configuración a la tabla users (migración legacy)."""
    conn = sqlite3.connect('data/trading_bot.db')
    cursor = conn.cursor()

    columns = [
        ("max_exposure_percent", "FLOAT DEFAULT 80.0"),
        ("cooldown_minutes", "INTEGER DEFAULT 120"),
        ("invest_percentage_ranging", "FLOAT DEFAULT 15.0"),
        ("risk_profile", "VARCHAR DEFAULT 'agresivo'"),
        ("use_vwap_filter", "BOOLEAN DEFAULT 0"),
        ("use_daily_open_filter", "BOOLEAN DEFAULT 0"),
    ]

    for col_name, col_def in columns:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}')
            print(f"Added {col_name}")
        except sqlite3.OperationalError as e:
            print(f"{col_name} might exist: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    alter_db()
