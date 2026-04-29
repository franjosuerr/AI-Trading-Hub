import sqlite3

def alter_db():
    """Agrega columnas de configuración a la tabla users (migración legacy)."""
    conn = sqlite3.connect('data/trading_bot.db')
    cursor = conn.cursor()

    columns = [
        ("max_exposure_percent", "FLOAT DEFAULT 40.0"),
        ("cooldown_minutes", "INTEGER DEFAULT 180"),
        ("invest_percentage_ranging", "FLOAT DEFAULT 10.0"),
        ("risk_profile", "VARCHAR DEFAULT 'conservador'"),
        ("use_vwap_filter", "BOOLEAN DEFAULT 1"),
        ("use_daily_open_filter", "BOOLEAN DEFAULT 0"),
        ("fee_rate", "FLOAT DEFAULT 0.1"),
        ("prod_gate_enabled", "BOOLEAN DEFAULT 1"),
        ("prod_gate_lookback_days", "INTEGER DEFAULT 7"),
        ("prod_gate_min_trades", "INTEGER DEFAULT 8"),
        ("prod_gate_min_win_rate", "FLOAT DEFAULT 48.0"),
        ("prod_gate_min_net_profit_pct", "FLOAT DEFAULT 0.0"),
        ("prod_gate_max_drawdown_pct", "FLOAT DEFAULT 3.0"),
        ("daily_loss_limit_pct", "FLOAT DEFAULT 1.5"),
        ("weekly_loss_limit_pct", "FLOAT DEFAULT 4.0"),
    ]

    # Columnas para tabla trades
    trade_columns = [
        ("partial_exit_done", "BOOLEAN DEFAULT 0"),
    ]

    for col_name, col_def in trade_columns:
        try:
            cursor.execute(f'ALTER TABLE trades ADD COLUMN {col_name} {col_def}')
            print(f"Added trades.{col_name}")
        except sqlite3.OperationalError as e:
            print(f"trades.{col_name} might exist: {e}")

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
