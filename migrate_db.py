import sqlite3

def migrate():
    try:
        conn = sqlite3.connect('data/trading_bot.db')
        c = conn.cursor()
        
        # Array of new columns to add
        columns = [
            ("ema_fast", "INTEGER DEFAULT 7"),
            ("ema_slow", "INTEGER DEFAULT 30"),
            ("adx_period", "INTEGER DEFAULT 14"),
            ("adx_threshold", "INTEGER DEFAULT 25"),
            ("invest_percentage", "REAL DEFAULT 75.0"),
        ]
        
        for col_name, col_def in columns:
            try:
                c.execute(f"ALTER TABLE global_config ADD COLUMN {col_name} {col_def}")
                print(f"Added column {col_name} to global_config.")
            except sqlite3.OperationalError as e:
                # Si la columna ya existe, ignora el error
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col_name} already exists.")
                else:
                    print(f"Error adding {col_name}: {e}")
                    
        conn.commit()
        conn.close()
        print("Migration complete!")
    except Exception as e:
        print(f"Failed to migrate database: {e}")

if __name__ == '__main__':
    migrate()
