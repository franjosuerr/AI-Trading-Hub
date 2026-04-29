import sqlite3

def migrate():
    """Agrega columnas de configuración de trading a la tabla users."""
    try:
        conn = sqlite3.connect('data/trading_bot.db')
        c = conn.cursor()
        
        columns = [
            ("ema_fast", "INTEGER DEFAULT 7"),
            ("ema_slow", "INTEGER DEFAULT 30"),
            ("adx_period", "INTEGER DEFAULT 14"),
            ("adx_threshold", "INTEGER DEFAULT 28"),
            ("invest_percentage", "REAL DEFAULT 10.0"),
            ("invest_percentage_ranging", "REAL DEFAULT 10.0"),
            ("trailing_stop_activation", "REAL DEFAULT 2.5"),
            ("trailing_stop_distance", "REAL DEFAULT 0.55"),
            ("macro_timeframe", "VARCHAR DEFAULT '1h'"),
            ("risk_profile", "VARCHAR DEFAULT 'conservador'"),
            ("use_vwap_filter", "BOOLEAN DEFAULT 1"),
            ("use_daily_open_filter", "BOOLEAN DEFAULT 0"),
            ("fee_rate", "REAL DEFAULT 0.1"),
            ("prod_gate_enabled", "BOOLEAN DEFAULT 1"),
            ("prod_gate_lookback_days", "INTEGER DEFAULT 7"),
            ("prod_gate_min_trades", "INTEGER DEFAULT 8"),
            ("prod_gate_min_win_rate", "REAL DEFAULT 48.0"),
            ("prod_gate_min_net_profit_pct", "REAL DEFAULT 0.0"),
            ("prod_gate_max_drawdown_pct", "REAL DEFAULT 3.0"),
            ("daily_loss_limit_pct", "REAL DEFAULT 1.5"),
            ("weekly_loss_limit_pct", "REAL DEFAULT 4.0"),
        ]
        
        for col_name, col_def in columns:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                print(f"Added column {col_name} to users.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col_name} already exists.")
                else:
                    print(f"Error adding {col_name}: {e}")
                    
        # Eliminar tabla legacy si existe
        try:
            c.execute('DROP TABLE IF EXISTS global_config')
            print("Dropped legacy global_config table.")
        except Exception:
            pass

        conn.commit()
        conn.close()
        print("Migration complete!")
    except Exception as e:
        print(f"Failed to migrate database: {e}")

if __name__ == '__main__':
    migrate()
