import React, { useState, useEffect } from 'react';
import { Layout, Users, Activity, Settings, TrendingUp, Play, Square, Plus, Trash2, Bot, X, Save, LogOut, Lock, UserPlus, Shield, BarChart3, ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import axios from 'axios';
import logger from './utils/logger';

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

// ─── Axios con JWT ───
const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.clear();
      window.location.reload();
    }
    return Promise.reject(err);
  }
);

// ══════════════════════════════════════════════
// SETUP SCREEN
// ══════════════════════════════════════════════
function SetupScreen({ onSetup }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) { setError('Las contraseñas no coinciden'); return; }
    if (password.length < 6) { setError('La contraseña debe tener al menos 6 caracteres'); return; }
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/auth/setup`, { username, email, password });
      localStorage.setItem('auth_token', res.data.token);
      localStorage.setItem('auth_role', res.data.role);
      localStorage.setItem('auth_user_id', res.data.user_id);
      localStorage.setItem('auth_username', res.data.username);
      onSetup(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error de conexión');
    } finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-dark)', padding: '20px' }}>
      <div style={{ width: '100%', maxWidth: '460px', animation: 'fadeIn 0.6s ease' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{ background: 'linear-gradient(135deg, rgba(0, 255, 136, 0.1), rgba(0, 242, 255, 0.1))', width: '80px', height: '80px', borderRadius: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1.5rem', border: '1px solid rgba(0, 255, 136, 0.2)' }}>
            <Shield size={36} style={{ color: '#00ff88' }} />
          </div>
          <h1 style={{ fontSize: '2rem', fontWeight: '800', background: 'linear-gradient(to right, #00ff88, #00f2ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>CONFIGURACIÓN INICIAL</h1>
          <p style={{ color: 'var(--text-dim)', marginTop: '0.5rem' }}>Crea tu cuenta de administrador</p>
        </div>
        <form onSubmit={handleSubmit} className="card" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {error && <div style={{ background: 'rgba(255, 0, 85, 0.1)', color: '#ff5588', padding: '12px', borderRadius: '10px', fontSize: '0.9rem', border: '1px solid rgba(255, 0, 85, 0.2)', textAlign: 'center' }}>{error}</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontWeight: '600' }}>NOMBRE DE USUARIO</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Admin" required autoFocus />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontWeight: '600' }}>CORREO ELECTRÓNICO</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="tu@email.com" required />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontWeight: '600' }}>CONTRASEÑA</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••" required />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontWeight: '600' }}>CONFIRMAR</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="••••••" required />
            </div>
          </div>
          <button type="submit" className="btn-primary" disabled={loading} style={{ marginTop: '0.5rem', width: '100%', padding: '16px', fontSize: '1rem', fontWeight: '700', opacity: loading ? 0.7 : 1 }}>
            {loading ? 'CREANDO...' : 'CREAR CUENTA ADMIN'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// LOGIN SCREEN
// ══════════════════════════════════════════════
function LoginScreen({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/auth/login`, { email, password });
      localStorage.setItem('auth_token', res.data.token);
      localStorage.setItem('auth_role', res.data.role);
      localStorage.setItem('auth_user_id', res.data.user_id);
      localStorage.setItem('auth_username', res.data.username);
      onLogin(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error de conexión');
    } finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-dark)', padding: '20px' }}>
      <div style={{ width: '100%', maxWidth: '420px', animation: 'fadeIn 0.6s ease' }}>
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          <div style={{ background: 'linear-gradient(135deg, rgba(0, 242, 255, 0.1), rgba(112, 0, 255, 0.1))', width: '80px', height: '80px', borderRadius: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1.5rem', border: '1px solid rgba(0, 242, 255, 0.2)' }}>
            <Lock size={36} style={{ color: '#00f2ff' }} />
          </div>
          <h1 style={{ fontSize: '2rem', fontWeight: '800', background: 'linear-gradient(to right, #00f2ff, #7000ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>TRADING HUB</h1>
          <p style={{ color: 'var(--text-dim)', marginTop: '0.5rem' }}>Inicia sesión para continuar</p>
        </div>
        <form onSubmit={handleSubmit} className="card" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {error && <div style={{ background: 'rgba(255, 0, 85, 0.1)', color: '#ff5588', padding: '12px', borderRadius: '10px', fontSize: '0.9rem', border: '1px solid rgba(255, 0, 85, 0.2)', textAlign: 'center' }}>{error}</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: '600' }}>CORREO ELECTRÓNICO</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="tu@email.com" required autoFocus />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: '600' }}>CONTRASEÑA</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required />
          </div>
          <button type="submit" className="btn-primary" disabled={loading} style={{ marginTop: '0.5rem', width: '100%', padding: '16px', fontSize: '1rem', fontWeight: '700', opacity: loading ? 0.7 : 1 }}>
            {loading ? 'VERIFICANDO...' : 'INICIAR SESIÓN'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// STATS MODAL
// ══════════════════════════════════════════════
function UserStatsModal({ userId, userName, onClose }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(null);
  const [balanceLoading, setBalanceLoading] = useState(true);
  const [currentMonth, setCurrentMonth] = useState(() => {
    const p = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    return `${p.find(x => x.type === 'year').value}-${p.find(x => x.type === 'month').value}`;
  });

  useEffect(() => { fetchStats(); }, [currentMonth]);
  useEffect(() => { fetchBalance(); }, []);

  const fetchBalance = async () => {
    setBalanceLoading(true);
    try {
      const res = await api.get(`/stats/${userId}/balance`);
      setBalance(res.data);
    } catch (err) { console.error('Error fetching balance:', err); }
    finally { setBalanceLoading(false); }
  };

  const fetchStats = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/stats/${userId}/monthly?month=${currentMonth}`);
      setStats(res.data);
    } catch (err) { console.error('Error fetching stats:', err); }
    finally { setLoading(false); }
  };

  const changeMonth = (delta) => {
    const [y, m] = currentMonth.split('-').map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    setCurrentMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  };

  const monthLabel = (() => {
    const [y, m] = currentMonth.split('-').map(Number);
    const months = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
    return `${months[m - 1]} ${y}`;
  })();

  const s = stats?.summary || {};

  return (
    <div className="modal-overlay">
      <div className="card modal-content" style={{ width: '96%', maxWidth: '1200px', maxHeight: '95vh', overflow: 'auto', padding: '2rem', background: 'var(--bg-dark)', border: '1px solid rgba(0, 242, 255, 0.3)' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <h2 style={{ fontSize: '1.4rem', fontWeight: '800', color: '#00f2ff' }}>📊 Estadísticas</h2>
            <span style={{ color: 'var(--text-dim)', fontSize: '0.85rem' }}>— {userName}</span>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}><X size={24} /></button>
        </div>

        {/* ─── Row 1: Saldo + Métricas ─── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '1.5rem' }}>
          {/* Saldo CoinEx */}
          <div>
            <h3 style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontWeight: '700', marginBottom: '10px', letterSpacing: '1px' }}>SALDO EN COINEX</h3>
            {balanceLoading ? (
              <div className="glass-panel" style={{ padding: '20px', textAlign: 'center', color: 'var(--text-dim)' }}>Consultando saldo...</div>
            ) : balance?.error ? (
              <div className="glass-panel" style={{ padding: '14px', textAlign: 'center', color: '#ff5588', fontSize: '0.82rem' }}>⚠️ {balance.error}</div>
            ) : balance?.balances?.length > 0 ? (
              <div>
                <div className="glass-panel" style={{ padding: '16px', marginBottom: '10px', textAlign: 'center', background: 'rgba(0,255,136,0.03)', border: '1px solid rgba(0,255,136,0.15)' }}>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-dim)', fontWeight: '600', marginBottom: '4px' }}>VALOR TOTAL ESTIMADO</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: '900', color: '#00ff88' }}>${balance.total_usdt.toLocaleString('en', { minimumFractionDigits: 2 })}</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '6px' }}>
                  {balance.balances.map((b) => (
                    <div key={b.currency} className="glass-panel" style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                        <span style={{ fontWeight: '700', fontSize: '0.82rem' }}>{b.currency}</span>
                        <span style={{ fontSize: '0.7rem', color: '#00ff88' }}>${b.usdt_value.toLocaleString('en', { minimumFractionDigits: 2 })}</span>
                      </div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                        {b.free}{b.used > 0 && <span style={{ marginLeft: '6px', color: '#ffaa00' }}>({b.used} en uso)</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="glass-panel" style={{ padding: '14px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '0.82rem' }}>Sin saldo disponible</div>
            )}
          </div>

          {/* Métricas del mes */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
              <h3 style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontWeight: '700', letterSpacing: '1px' }}>RENDIMIENTO</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button onClick={() => changeMonth(-1)} className="btn-action" style={{ padding: '4px 8px' }}><ChevronLeft size={14} /></button>
                <span style={{ fontSize: '0.82rem', fontWeight: '700', minWidth: '120px', textAlign: 'center' }}>{monthLabel}</span>
                <button onClick={() => changeMonth(1)} className="btn-action" style={{ padding: '4px 8px' }}><ChevronRight size={14} /></button>
              </div>
            </div>
            {loading ? (
              <div className="glass-panel" style={{ padding: '20px', textAlign: 'center', color: 'var(--text-dim)' }}>Cargando...</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
                {[
                  { label: 'TRADES', value: s.total_trades || 0, color: '#00f2ff' },
                  { label: 'PROFIT', value: `$${(s.total_profit || 0).toFixed(4)}`, color: (s.total_profit || 0) >= 0 ? '#00ff88' : '#ff5588' },
                  { label: 'WIN RATE', value: `${(s.win_rate || 0).toFixed(1)}%`, color: (s.win_rate || 0) >= 50 ? '#00ff88' : '#ff5588' },
                  { label: 'PROMEDIO', value: `$${(s.avg_profit || 0).toFixed(4)}`, color: (s.avg_profit || 0) >= 0 ? '#00ff88' : '#ff5588' },
                  { label: 'MEJOR', value: `$${(s.best_trade || 0).toFixed(4)}`, color: '#00ff88' },
                  { label: 'PEOR', value: `$${(s.worst_trade || 0).toFixed(4)}`, color: '#ff5588' },
                  { label: 'VOLUMEN', value: `$${(s.total_volume || 0).toFixed(2)}`, color: '#00f2ff' },
                  { label: 'GANADOS', value: s.winning_trades || 0, color: '#00ff88' },
                  { label: 'PERDIDOS', value: s.losing_trades || 0, color: '#ff5588' },
                ].map((m, i) => (
                  <div key={i} className="glass-panel" style={{ padding: '10px', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.58rem', color: 'var(--text-dim)', fontWeight: '600', marginBottom: '4px' }}>{m.label}</div>
                    <div style={{ fontSize: '1rem', fontWeight: '800', color: m.color }}>{m.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ─── Row 2: Charts ─── */}
        {!loading && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: '16px', marginBottom: '1.5rem' }}>
              <div className="glass-panel" style={{ padding: '16px' }}>
                <h3 style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontWeight: '700', marginBottom: '12px' }}>PROFIT ACUMULADO</h3>
                {(stats?.profit_timeline || []).length > 0 ? (
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={stats.profit_timeline}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="date" tick={{ fill: '#666', fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fill: '#666', fontSize: 9 }} />
                      <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid rgba(0,242,255,0.3)', borderRadius: '8px', color: '#fff' }} />
                      <Line type="monotone" dataKey="cumulative" stroke="#00f2ff" strokeWidth={2} dot={{ r: 2, fill: '#00f2ff' }} name="Acumulado" />
                      <Line type="monotone" dataKey="daily" stroke="#7000ff" strokeWidth={1} strokeDasharray="5 5" dot={false} name="Diario" />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', fontSize: '0.85rem' }}>Sin datos este mes</div>}
              </div>
              <div className="glass-panel" style={{ padding: '16px' }}>
                <h3 style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontWeight: '700', marginBottom: '12px' }}>COMPRA / VENTA</h3>
                {(s.total_buys || 0) + (s.total_sells || 0) > 0 ? (
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie data={stats.buy_sell_ratio} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={65} paddingAngle={5} label={({ name, value }) => `${name}: ${value}`}>
                        {(stats?.buy_sell_ratio || []).map((_, i) => <Cell key={i} fill={i === 0 ? '#00f2ff' : '#ff5588'} />)}
                      </Pie>
                      <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid rgba(0,242,255,0.3)', borderRadius: '8px', color: '#fff' }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', fontSize: '0.85rem' }}>Sin datos</div>}
              </div>
            </div>
            {(stats?.trades_by_pair || []).length > 0 && (
              <div className="glass-panel" style={{ padding: '16px', marginBottom: '1.5rem' }}>
                <h3 style={{ fontSize: '0.7rem', color: 'var(--text-dim)', fontWeight: '700', marginBottom: '12px' }}>TRADES POR PAR</h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={stats.trades_by_pair}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="pair" tick={{ fill: '#999', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#666', fontSize: 9 }} />
                    <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid rgba(0,242,255,0.3)', borderRadius: '8px', color: '#fff' }} />
                    <Legend />
                    <Bar dataKey="buys" fill="#00f2ff" name="Compras" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="sells" fill="#ff5588" name="Ventas" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            {(stats?.recent_trades || []).length > 0 && (
              <div className="glass-panel" style={{ padding: '20px' }}>
                <h3 style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: '700', marginBottom: '16px' }}>ÚLTIMOS TRADES</h3>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                        <th style={{ textAlign: 'left', padding: '8px', color: 'var(--text-dim)' }}>FECHA</th>
                        <th style={{ textAlign: 'left', padding: '8px', color: 'var(--text-dim)' }}>PAR</th>
                        <th style={{ textAlign: 'center', padding: '8px', color: 'var(--text-dim)' }}>LADO</th>
                        <th style={{ textAlign: 'right', padding: '8px', color: 'var(--text-dim)' }}>CANTIDAD</th>
                        <th style={{ textAlign: 'right', padding: '8px', color: 'var(--text-dim)' }}>PRECIO</th>
                        <th style={{ textAlign: 'right', padding: '8px', color: 'var(--text-dim)' }}>PROFIT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.recent_trades.map((t, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                          <td style={{ padding: '8px', color: '#999' }}>{new Date(t.timestamp).toLocaleString('es', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'America/Bogota' })}</td>
                          <td style={{ padding: '8px', fontWeight: '600' }}>{t.pair}</td>
                          <td style={{ padding: '8px', textAlign: 'center' }}>
                            <span style={{ background: t.side === 'buy' ? 'rgba(0,242,255,0.1)' : 'rgba(255,85,136,0.1)', color: t.side === 'buy' ? '#00f2ff' : '#ff5588', padding: '2px 8px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: '700' }}>
                              {t.side === 'buy' ? 'COMPRA' : 'VENTA'}
                            </span>
                          </td>
                          <td style={{ padding: '8px', textAlign: 'right' }}>{t.amount}</td>
                          <td style={{ padding: '8px', textAlign: 'right' }}>${t.price}</td>
                          <td style={{ padding: '8px', textAlign: 'right', color: t.profit >= 0 ? '#00ff88' : '#ff5588', fontWeight: '600' }}>${t.profit.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {s.total_trades === 0 && (
              <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>
                <BarChart3 size={48} style={{ marginBottom: '1rem', opacity: 0.3 }} />
                <p>No hay trades registrados en {monthLabel}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// DASHBOARD
// ══════════════════════════════════════════════
function Dashboard({ userRole, userId, username, onLogout }) {
  const isAdmin = userRole === 'admin';
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState({ total_users: 0, active_bots: 0, total_profit: 0 });
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [formData, setFormData] = useState({ username: '', email: '', coinex_api_key: '', coinex_secret: '', telegram_bot_token: '', telegram_chat_id: '', password: '' });
  const [globalConfig, setGlobalConfig] = useState({
    interval: 300, test_mode: false,
    pairs: 'SOL/USDT,ETH/USDT,BTC/USDT,XRP/USDT', timeframe: '15m', candle_count: 350,
    pair_delay: 2, max_trades_per_day: 10, stop_loss_percent: 3.0, max_exposure_percent: 80.0, cooldown_minutes: 120, log_level: 'INFO',
    ema_fast: 7, ema_slow: 30, adx_period: 14, adx_threshold: 25, invest_percentage: 25.0, invest_percentage_ranging: 15.0, risk_profile: 'suave',
    use_vwap_filter: true, use_daily_open_filter: true
  });
  const [isGlobalModalOpen, setIsGlobalModalOpen] = useState(false);
  const [statsUserId, setStatsUserId] = useState(null);
  const [statsUserName, setStatsUserName] = useState('');

  useEffect(() => { fetchData(); const interval = setInterval(fetchData, 10000); return () => clearInterval(interval); }, []);

  const fetchData = async () => {
    try {
      const [usersRes, statsRes, configRes] = await Promise.all([
        api.get('/users/'), api.get('/stats/summary'), api.get('/config/')
      ]);

      // Update users list and stats
      setStats(statsRes.data);

      // Only update the form states if the modals are NOT currently open
      setUsers(prev => {
        if (!isModalOpen) return usersRes.data;
        // If the user modal is open, we update the main list but we shouldn't wipe their editing form
        // (form is separate state anyway, but just in case, updating users is safe)
        return usersRes.data;
      });

      setGlobalConfig(prev => {
        if (!isGlobalModalOpen) return configRes.data;
        return prev;
      });
      setLoading(false);
    } catch (error) { logger.error("Error al obtener datos", { error: error.message }); }
  };

  const toggleBot = async (uid, isActive) => {
    try { await api.post(`/bot/${uid}/${isActive ? 'stop' : 'start'}`); fetchData(); }
    catch (error) { alert(error.response?.data?.detail || "Error al controlar el bot"); }
  };

  const handleOpenModal = (user = null) => {
    if (user) {
      setCurrentUser(user);
      setFormData({ username: user.username, email: user.email || '', coinex_api_key: user.coinex_api_key || '', coinex_secret: user.coinex_secret || '', telegram_bot_token: user.telegram_bot_token || '', telegram_chat_id: user.telegram_chat_id || '', password: '' });
    } else {
      setCurrentUser(null);
      setFormData({ username: '', email: '', coinex_api_key: '', coinex_secret: '', telegram_bot_token: '', telegram_chat_id: '', password: '' });
    }
    setIsModalOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      if (currentUser) {
        const data = { ...formData };
        if (!data.password) delete data.password;
        await api.put(`/users/${currentUser.id}`, data);
      } else {
        if (!formData.password) { alert("La contraseña es obligatoria para nuevos usuarios"); return; }
        await api.post('/users/', formData);
      }
      setIsModalOpen(false);
      fetchData();
    } catch (error) { alert(error.response?.data?.detail || "Error al guardar"); }
  };

  const handleDelete = async (uid) => {
    if (window.confirm("¿Estás seguro de eliminar este usuario?")) {
      try { await api.delete(`/users/${uid}`); fetchData(); }
      catch (error) { alert(error.response?.data?.detail || "Error al eliminar"); }
    }
  };

  const handleSaveGlobal = async (e) => {
    e.preventDefault();
    try { await api.post('/config/', globalConfig); setIsGlobalModalOpen(false); fetchData(); }
    catch (error) { alert(error.response?.data?.detail || "Error al guardar configuración"); }
  };

  const handleRiskChange = (e) => {
    const profile = e.target.value;
    let overrides = { risk_profile: profile };
    if (profile === 'suave') {
      overrides = { ...overrides, invest_percentage: 10.0, invest_percentage_ranging: 5.0, ema_fast: 12, ema_slow: 26, stop_loss_percent: 2.0, trailing_stop_activation: 1.5, trailing_stop_distance: 0.5 };
    } else if (profile === 'conservador') {
      overrides = { ...overrides, invest_percentage: 25.0, invest_percentage_ranging: 15.0, ema_fast: 7, ema_slow: 30, stop_loss_percent: 3.0, trailing_stop_activation: 1.5, trailing_stop_distance: 0.5 };
    } else if (profile === 'agresivo') {
      overrides = { ...overrides, invest_percentage: 50.0, invest_percentage_ranging: 30.0, ema_fast: 5, ema_slow: 20, stop_loss_percent: 4.0, trailing_stop_activation: 2.0, trailing_stop_distance: 1.0 };
    } else if (profile === 'muy_agresivo') {
      overrides = { ...overrides, invest_percentage: 90.0, invest_percentage_ranging: 50.0, ema_fast: 3, ema_slow: 10, stop_loss_percent: 6.0, trailing_stop_activation: 3.0, trailing_stop_distance: 1.5 };
    }
    setGlobalConfig({ ...globalConfig, ...overrides });
  };

  const downloadLog = async (uid, uname) => {
    try {
      const res = await api.get(`/logs/bot/${uid}/download`, { responseType: 'blob' });
      const p = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
      const today = `${p.find(x => x.type === 'year').value}-${p.find(x => x.type === 'month').value}-${p.find(x => x.type === 'day').value}`;
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/plain' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `bot_${uname}_${today}.log`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      alert(error.response?.status === 404 ? 'No hay logs disponibles para hoy' : 'Error al descargar logs');
    }
  };

  return (
    <div>
      {/* ─── Top Bar ─── */}
      <nav className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span className="topbar-logo">TRADING HUB</span>
          {isAdmin && <span style={{ background: 'rgba(0,255,136,0.1)', color: '#00ff88', padding: '3px 10px', borderRadius: '6px', fontSize: '0.6rem', fontWeight: '700', letterSpacing: '0.5px' }}>ADMIN</span>}
          {!isAdmin && <span style={{ color: 'var(--text-dim)', fontSize: '0.85rem' }}>Hola, {username}</span>}
        </div>
        {isAdmin && (
          <div className="topbar-stats">
            <div className="topbar-stat"><div className="topbar-stat-label">Usuarios</div><div className="topbar-stat-value">{stats.total_users}</div></div>
            <div className="topbar-stat"><div className="topbar-stat-label">Activos</div><div className="topbar-stat-value" style={{ color: '#00f2ff' }}>{stats.active_bots}</div></div>
            <div className="topbar-stat"><div className="topbar-stat-label">Profit Total</div><div className="topbar-stat-value" style={{ color: '#00ff88' }}>${stats.total_profit?.toFixed(2) || '0.00'}</div></div>
          </div>
        )}
        <div className="topbar-actions">
          {isAdmin && (
            <button onClick={() => setIsGlobalModalOpen(true)} className="btn-action"><Settings size={15} /> Config Global</button>
          )}
          <button onClick={onLogout} className="btn-action" style={{ color: '#ff5588', borderColor: 'rgba(255,0,85,0.2)' }}><LogOut size={15} /> Salir</button>
        </div>
      </nav>

      {/* ─── Page Content ─── */}
      <div className="page-content">
        <div style={{ marginBottom: '1.5rem', animation: 'fadeIn 0.6s ease' }}>
          <h2 style={{ fontSize: '1.4rem', fontWeight: '700' }}>Bienvenido, {username} 👋</h2>
          <p style={{ color: 'var(--text-dim)', fontSize: '0.85rem', marginTop: '4px' }}>
            {isAdmin ? 'Aquí tienes el resumen de todos los bots del sistema.' : 'Aquí puedes gestionar y monitorear tu bot de trading.'}
          </p>
        </div>
        <div className="section-header">
          <span className="section-title">{isAdmin ? 'Todos los Bots' : 'Mi Bot'}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>{users.length} usuario{users.length !== 1 ? 's' : ''}</span>
        </div>

        <section className="grid grid-users">
          {users.map((user) => (
            <div key={user.id} className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ background: user.is_active ? 'rgba(0,255,136,0.1)' : 'rgba(112,0,255,0.08)', padding: '10px', borderRadius: '12px', color: user.is_active ? '#00ff88' : '#7000ff' }}>
                    <Bot size={22} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.15rem', fontWeight: '700' }}>{user.username}</h3>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                      <span className={`status-badge ${user.is_active ? 'status-active' : 'status-inactive'}`}>{user.is_active ? 'ACTIVO' : 'DETENIDO'}</span>
                      {user.role === 'admin' && <span style={{ fontSize: '0.55rem', background: 'rgba(0,255,136,0.08)', color: '#00ff88', padding: '2px 6px', borderRadius: '4px', fontWeight: '700' }}>ADMIN</span>}
                    </div>
                    <div style={{ marginTop: '6px', fontSize: '0.8rem', fontWeight: '700', color: (user.total_profit || 0) >= 0 ? '#00ff88' : '#ff5588' }}>
                      Profit: ${(user.total_profit || 0).toFixed(4)}
                    </div>
                  </div>
                </div>
                <button onClick={() => toggleBot(user.id, user.is_active)} style={{ background: user.is_active ? 'rgba(255,0,85,0.08)' : 'rgba(0,255,136,0.08)', color: user.is_active ? '#ff0055' : '#00ff88', border: 'none', padding: '11px', borderRadius: '50%', cursor: 'pointer', transition: 'all 0.2s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {user.is_active ? <Square size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
                </button>
              </div>

              <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 16px', borderRadius: '12px', marginBottom: '1.2rem', fontSize: '0.82rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ color: 'var(--text-dim)' }}>CoinEx API</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{user.coinex_api_key ? '••••' + user.coinex_api_key.slice(-4) : <em style={{ color: 'var(--text-dim)' }}>sin configurar</em>}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ color: 'var(--text-dim)' }}>Telegram</span>
                  <span>{user.telegram_chat_id || <em style={{ color: 'var(--text-dim)' }}>sin configurar</em>}</span>
                </div>
                {isAdmin && <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-dim)' }}>Email</span>
                  <span style={{ fontSize: '0.8rem' }}>{user.email || '—'}</span>
                </div>}
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => { setStatsUserId(user.id); setStatsUserName(user.username); }} className="btn-action" style={{ color: '#00f2ff', borderColor: 'rgba(0,242,255,0.15)' }}><BarChart3 size={15} /> Stats</button>
                <button onClick={() => downloadLog(user.id, user.username)} className="btn-action" style={{ color: '#ffaa00', borderColor: 'rgba(255,170,0,0.15)' }}><Download size={15} /> Logs</button>
                <button onClick={() => handleOpenModal(user)} className="btn-primary" style={{ flex: 1, padding: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}><Settings size={14} /> Ajustes</button>
                {isAdmin && <button onClick={() => handleDelete(user.id)} className="btn-action" style={{ color: '#ff0055', borderColor: 'rgba(255,0,85,0.15)', padding: '8px 10px' }}><Trash2 size={15} /></button>}
              </div>
            </div>
          ))}

          {/* Tarjeta Añadir Usuario — solo admin */}
          {isAdmin && (
            <div onClick={() => handleOpenModal()} className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', borderStyle: 'dashed', borderColor: 'rgba(255,255,255,0.12)', cursor: 'pointer', background: 'transparent', minHeight: '260px' }}>
              <div style={{ background: 'var(--glass)', padding: '20px', borderRadius: '50%', marginBottom: '1rem', color: 'var(--text-dim)' }}>
                <UserPlus size={32} />
              </div>
              <span style={{ fontWeight: '600', color: 'var(--text-dim)' }}>AÑADIR NUEVO USUARIO</span>
            </div>
          )}
        </section>
      </div>

      {/* ─── Modal de Usuario ─── */}
      {isModalOpen && (
        <div className="modal-overlay">
          <div className="card modal-content" style={{ width: '95%', maxWidth: '550px', padding: '2rem', background: 'var(--bg-dark)', border: '1px solid rgba(0,242,255,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1.5rem', fontWeight: '800' }}>{currentUser ? 'EDITAR USUARIO' : 'NUEVO USUARIO'}</h2>
              <button onClick={() => setIsModalOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}><X size={24} /></button>
            </div>
            <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>USUARIO</label>
                  <input value={formData.username} onChange={(e) => setFormData({ ...formData, username: e.target.value })} required />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>EMAIL</label>
                  <input type="email" value={formData.email} onChange={(e) => setFormData({ ...formData, email: e.target.value })} required />
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>{currentUser ? 'NUEVA CONTRASEÑA (dejar vacío = no cambiar)' : 'CONTRASEÑA'}</label>
                <input type="password" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })} required={!currentUser} placeholder={currentUser ? '••••••••' : ''} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>COINEX API KEY</label>
                  <input value={formData.coinex_api_key} onChange={(e) => setFormData({ ...formData, coinex_api_key: e.target.value })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>COINEX SECRET</label>
                  <input type="password" value={formData.coinex_secret} onChange={(e) => setFormData({ ...formData, coinex_secret: e.target.value })} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>TELEGRAM TOKEN</label>
                  <input value={formData.telegram_bot_token} onChange={(e) => setFormData({ ...formData, telegram_bot_token: e.target.value })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>TELEGRAM CHAT ID</label>
                  <input value={formData.telegram_chat_id} onChange={(e) => setFormData({ ...formData, telegram_chat_id: e.target.value })} />
                </div>
              </div>
              <button type="submit" className="btn-primary" style={{ marginTop: '0.5rem', width: '100%', padding: '15px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
                <Save size={18} /> GUARDAR
              </button>
            </form>
          </div>
        </div>
      )}

      {/* ─── Modal Config Global ─── */}
      {isAdmin && isGlobalModalOpen && (
        <div className="modal-overlay">
          <div className="card modal-content" style={{ width: '95%', maxWidth: '750px', padding: '2rem', background: 'var(--bg-dark)', border: '1px solid rgba(112,0,255,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1.5rem', fontWeight: '800', color: 'var(--secondary)' }}>AJUSTES GLOBALES</h2>
              <button onClick={() => setIsGlobalModalOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}><X size={24} /></button>
            </div>
            <form onSubmit={handleSaveGlobal} style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxHeight: '70vh', overflowY: 'auto', paddingRight: '10px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '15px', background: 'linear-gradient(135deg, rgba(0, 242, 255, 0.05), rgba(112, 0, 255, 0.05))', borderRadius: '12px', border: '1px solid rgba(0, 242, 255, 0.2)' }}>
                <label style={{ fontSize: '0.85rem', color: '#00f2ff', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <TrendingUp size={16} /> PERFIL DE RIESGO DEL BOT
                </label>
                <select 
                  value={globalConfig.risk_profile} 
                  onChange={handleRiskChange}
                  style={{ padding: '12px', borderRadius: '8px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', fontSize: '1rem', fontWeight: '600' }}
                >
                  <option value="suave">🟢 Suave (Bajo Beneficio / Bajo Riesgo)</option>
                  <option value="conservador">🔵 Conservador (Recomendado)</option>
                  <option value="agresivo">🟠 Agresivo (Alto Capital / Rápido)</option>
                  <option value="muy_agresivo">🔴 Muy Agresivo (ALL IN / Filtros Apagados)</option>
                  <option value="personalizado">⚙️ Personalizado (Ajuste Manual)</option>
                </select>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '4px' }}>
                  Al seleccionar un perfil, los parámetros debajo se auto-ajustarán y los filtros anti-caída variarán.
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(0,242,255,0.05)', borderRadius: '8px', border: '1px solid rgba(0,242,255,0.15)' }}>
                <h3 style={{ fontSize: '0.8rem', color: '#00f2ff', marginBottom: '12px', fontWeight: '700' }}>ESTRATEGIA DUAL (Tendencia + Rango)</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px', marginBottom: '12px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>EMA FAST (Corto)</label>
                    <input type="number" value={globalConfig.ema_fast} onChange={(e) => setGlobalConfig({ ...globalConfig, ema_fast: parseInt(e.target.value) })} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>EMA SLOW (Largo)</label>
                    <input type="number" value={globalConfig.ema_slow} onChange={(e) => setGlobalConfig({ ...globalConfig, ema_slow: parseInt(e.target.value) })} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px', marginBottom: '12px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>% INVERSIÓN TENDENCIA</label>
                    <input type="number" step="0.1" value={globalConfig.invest_percentage} onChange={(e) => setGlobalConfig({ ...globalConfig, invest_percentage: parseFloat(e.target.value) })} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>% INVERSIÓN RANGO</label>
                    <input type="number" step="0.1" value={globalConfig.invest_percentage_ranging || 15} onChange={(e) => setGlobalConfig({ ...globalConfig, invest_percentage_ranging: parseFloat(e.target.value) })} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>ADX PERIODO</label>
                    <input type="number" value={globalConfig.adx_period} onChange={(e) => setGlobalConfig({ ...globalConfig, adx_period: parseInt(e.target.value) })} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>ADX UMBRAL (Tendencia)</label>
                    <input type="number" value={globalConfig.adx_threshold} onChange={(e) => setGlobalConfig({ ...globalConfig, adx_threshold: parseInt(e.target.value) })} />
                  </div>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>CANDLE COUNT</label>
                  <input type="number" value={globalConfig.candle_count} onChange={(e) => setGlobalConfig({ ...globalConfig, candle_count: parseInt(e.target.value) })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>INTERVALO (SEG)</label>
                  <input type="number" value={globalConfig.interval} onChange={(e) => setGlobalConfig({ ...globalConfig, interval: parseInt(e.target.value) })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>PAIR DELAY</label>
                  <input type="number" value={globalConfig.pair_delay} onChange={(e) => setGlobalConfig({ ...globalConfig, pair_delay: parseInt(e.target.value) })} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>TRADES/DÍA</label>
                  <input type="number" value={globalConfig.max_trades_per_day} onChange={(e) => setGlobalConfig({ ...globalConfig, max_trades_per_day: parseInt(e.target.value) })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>STOP LOSS %</label>
                  <input type="number" step="0.1" value={globalConfig.stop_loss_percent} onChange={(e) => setGlobalConfig({ ...globalConfig, stop_loss_percent: parseFloat(e.target.value) })} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>MAX EXPOSICIÓN %</label>
                  <input type="number" step="0.1" value={globalConfig.max_exposure_percent} onChange={(e) => setGlobalConfig({ ...globalConfig, max_exposure_percent: parseFloat(e.target.value) })} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>COOLDOWN (MIN)</label>
                  <input type="number" value={globalConfig.cooldown_minutes} onChange={(e) => setGlobalConfig({ ...globalConfig, cooldown_minutes: parseInt(e.target.value) })} />
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(255,170,0,0.05)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(255,170,0,0.2)' }}>
                <label style={{ fontSize: '0.85rem', color: '#ffaa00', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Shield size={16} /> FILTROS DAY-TRADING INTRADIARIOS (Protección Mercados Bajistas)
                </label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <input type="checkbox" id="useVwap" checked={globalConfig.use_vwap_filter} onChange={(e) => setGlobalConfig({ ...globalConfig, use_vwap_filter: e.target.checked })} style={{ width: '18px', height: '18px', accentColor: '#ffaa00' }} />
                  <div>
                    <label htmlFor="useVwap" style={{ fontWeight: '600', color: 'white' }}>Solo comprar por encima del VWAP Diario</label>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Evita falsos rebotes donde los institucionales tienen posición de venta.</div>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <input type="checkbox" id="useDailyOpen" checked={globalConfig.use_daily_open_filter} onChange={(e) => setGlobalConfig({ ...globalConfig, use_daily_open_filter: e.target.checked })} style={{ width: '18px', height: '18px', accentColor: '#ffaa00' }} />
                  <div>
                    <label htmlFor="useDailyOpen" style={{ fontWeight: '600', color: 'white' }}>Solo comprar si el Día Actual es Verde (Sobre Apertura)</label>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>No invierte nada si el token está cayendo a nivel intradiario (00:00 UTC).</div>
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', background: 'rgba(0,255,136,0.05)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(0,255,136,0.2)' }}>
                <input type="checkbox" id="testMode" checked={globalConfig.test_mode} onChange={(e) => setGlobalConfig({ ...globalConfig, test_mode: e.target.checked })} style={{ width: '20px', height: '20px', accentColor: 'var(--secondary)' }} />
                <label htmlFor="testMode" style={{ fontWeight: '600', color: '#00ff88' }}>MODO PRUEBA (SIMULACIÓN)</label>
              </div>
              <button type="submit" className="btn-primary" style={{ marginTop: '0.5rem', width: '100%', padding: '15px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', flexShrink: 0 }}>
                <Save size={18} /> APLICAR CAMBIOS GLOBALES
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Stats Modal */}
      {statsUserId && (
        <UserStatsModal userId={statsUserId} userName={statsUserName} onClose={() => setStatsUserId(null)} />
      )}
    </div>
  );
}

// ══════════════════════════════════════════════
// APP PRINCIPAL
// ══════════════════════════════════════════════
function App() {
  const [appState, setAppState] = useState('loading');
  const [userRole, setUserRole] = useState(localStorage.getItem('auth_role') || '');
  const [userId, setUserId] = useState(localStorage.getItem('auth_user_id') || '');
  const [username, setUsername] = useState(localStorage.getItem('auth_username') || '');

  useEffect(() => { checkAuthStatus(); }, []);

  const checkAuthStatus = async () => {
    if (localStorage.getItem('auth_token')) { setAppState('dashboard'); return; }
    try {
      const res = await axios.get(`${API_BASE}/auth/status`);
      setAppState(res.data.needs_setup ? 'setup' : 'login');
    } catch { setAppState('login'); }
  };

  const handleAuth = (data) => { setUserRole(data.role); setUserId(data.user_id); setUsername(data.username); setAppState('dashboard'); };
  const handleLogout = () => { localStorage.clear(); setUserRole(''); setUserId(''); setUsername(''); setAppState('login'); };

  if (appState === 'loading') return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-dark)', color: 'var(--text-dim)' }}>Cargando...</div>;
  if (appState === 'setup') return <SetupScreen onSetup={handleAuth} />;
  if (appState === 'login') return <LoginScreen onLogin={handleAuth} />;

  return <Dashboard userRole={userRole} userId={userId} username={username} onLogout={handleLogout} />;
}

export default App;
