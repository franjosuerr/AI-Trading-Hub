import React, { useState, useEffect } from 'react';
import { X, DollarSign, Plus, AlertTriangle, Shield } from 'lucide-react';
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");
const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export default function ManualOperationModal({ userId, userName, onClose }) {
  const [activeTab, setActiveTab] = useState('buy');
  const [positions, setPositions] = useState([]);
  const [eligiblePairs, setEligiblePairs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [operationLoading, setOperationLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [confirmPair, setConfirmPair] = useState(null);
  const [config, setConfig] = useState({ pairs: '' });

  useEffect(() => {
    fetchPositions();
    fetchConfig();
  }, []);

  const fetchPositions = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/stats/${userId}/open_positions?limit=100`);
      setPositions(res.data?.data || []);
    } catch (err) {
      setError('Error al cargar posiciones abiertas');
    } finally { setLoading(false); }
  };

  const fetchConfig = async () => {
    try {
      const res = await api.get(`/users/${userId}`);
      setConfig(res.data);
      // Filtrar pares elegibles para compra
      const allPairs = (res.data.pairs || '').split(',').map(p => p.trim()).filter(Boolean);
      setEligiblePairs(allPairs.filter(pair => !positions.some(pos => pos.pair === pair)));
    } catch (err) {
      setError('Error al cargar configuración del bot');
    }
  };

  const handleSell = async (pair) => {
    setOperationLoading(true);
    setResult(null);
    setError('');
    setConfirmPair(null);
    try {
      const res = await api.post(`/bot/${userId}/manual_sell`, { pair });
      setResult(res.data);
      setPositions(prev => prev.filter(p => p.pair !== pair));
      setEligiblePairs(prev => [...prev, pair]);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al ejecutar la venta manual');
    } finally { setOperationLoading(false); }
  };

  const handleBuy = async (pair) => {
    setOperationLoading(true);
    setResult(null);
    setError('');
    setConfirmPair(null);
    try {
      const res = await api.post(`/bot/${userId}/manual_buy`, { pair });
      setResult(res.data);
      setEligiblePairs(prev => prev.filter(p => p !== pair));
      setPositions(prev => [...prev, { pair, amount: res.data.amount, avg_entry_price: res.data.price, total_invested: res.data.invested }]);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al ejecutar la compra manual');
    } finally { setOperationLoading(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="card modal-content" style={{ width: '96%', maxWidth: '700px', maxHeight: '90vh', overflow: 'auto', padding: '2rem', background: 'var(--bg-dark)', border: '1px solid rgba(0, 242, 255, 0.3)' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ background: 'rgba(0,242,255,0.1)', padding: '10px', borderRadius: '12px' }}>
              <DollarSign size={22} style={{ color: '#00f2ff' }} />
            </div>
            <div>
              <h2 style={{ fontSize: '1.3rem', fontWeight: '800', color: '#00f2ff' }}>OPERACIÓN MANUAL</h2>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.8rem' }}>{userName}</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}><X size={24} /></button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '10px' }}>
          <button 
            onClick={() => setActiveTab('buy')}
            style={{ background: 'transparent', border: 'none', color: activeTab === 'buy' ? '#00ff88' : 'var(--text-dim)', fontSize: '0.85rem', fontWeight: '800', cursor: 'pointer', padding: '6px 12px', borderBottom: activeTab === 'buy' ? '2px solid #00ff88' : '2px solid transparent', transition: 'all 0.2s' }}
          >
            COMPRAR
          </button>
          <button 
            onClick={() => setActiveTab('sell')}
            style={{ background: 'transparent', border: 'none', color: activeTab === 'sell' ? '#ff5588' : 'var(--text-dim)', fontSize: '0.85rem', fontWeight: '800', cursor: 'pointer', padding: '6px 12px', borderBottom: activeTab === 'sell' ? '2px solid #ff5588' : '2px solid transparent', transition: 'all 0.2s' }}
          >
            VENDER
          </button>
        </div>

        {/* Aviso */}
        <div style={{ background: 'rgba(255,170,0,0.08)', border: '1px solid rgba(255,170,0,0.25)', padding: '12px 16px', borderRadius: '10px', fontSize: '0.82rem', color: '#ffaa00', marginBottom: '1.5rem', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
          <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>Solo puedes comprar monedas que no tengan posición abierta. Las ventas manuales cierran posiciones abiertas al precio de mercado.</span>
        </div>

        {/* Resultado exitoso */}
        {result && (
          <div style={{ background: 'rgba(0,255,136,0.08)', border: '1px solid rgba(0,255,136,0.25)', padding: '16px', borderRadius: '10px', marginBottom: '1.5rem' }}>
            <div style={{ fontWeight: '800', color: '#00ff88', marginBottom: '8px', fontSize: '0.95rem' }}>OPERACIÓN EJECUTADA</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.82rem' }}>
              <div><span style={{ color: 'var(--text-dim)' }}>Par:</span> <strong>{result.pair}</strong></div>
              <div><span style={{ color: 'var(--text-dim)' }}>Cantidad:</span> <strong>{result.amount}</strong></div>
              <div><span style={{ color: 'var(--text-dim)' }}>Precio:</span> <strong>${result.price}</strong></div>
              <div><span style={{ color: 'var(--text-dim)' }}>Invertido:</span> <strong>${result.invested}</strong></div>
              <div style={{ gridColumn: '1 / -1' }}>
                {result.profit !== undefined && (
                  <>
                    <span style={{ color: 'var(--text-dim)' }}>Profit:</span>{' '}
                    <strong style={{ color: result.profit >= 0 ? '#00ff88' : '#ff5588', fontSize: '1.1rem' }}>
                      {result.profit >= 0 ? '+' : ''}{result.profit} USDT
                    </strong>
                  </>
                )}
                {result.simulated && <span style={{ marginLeft: '8px', background: 'rgba(255,170,0,0.1)', color: '#ffaa00', padding: '2px 6px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: '700' }}>SIMULADA</span>}
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{ background: 'rgba(255,0,85,0.08)', border: '1px solid rgba(255,0,85,0.25)', color: '#ff5588', padding: '12px 16px', borderRadius: '10px', marginBottom: '1.5rem', fontSize: '0.85rem' }}>
            {error}
          </div>
        )}

        {/* Tab Content */}
        {activeTab === 'buy' ? (
          loading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>Cargando monedas elegibles...</div>
          ) : eligiblePairs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>
              <Shield size={40} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
              <p style={{ fontSize: '1rem', fontWeight: '600' }}>No hay monedas elegibles para comprar</p>
              <p style={{ fontSize: '0.82rem', marginTop: '4px' }}>Todas las monedas configuradas tienen posición abierta.</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                    <th style={{ textAlign: 'left', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>PAR</th>
                    <th style={{ textAlign: 'center', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>ACCIÓN</th>
                  </tr>
                </thead>
                <tbody>
                  {eligiblePairs.map((pair) => (
                    <tr key={pair} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '12px 8px', fontWeight: '700' }}>{pair}</td>
                      <td style={{ padding: '12px 8px', textAlign: 'center' }}>
                        {confirmPair === pair ? (
                          <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                            <button
                              onClick={() => handleBuy(pair)}
                              disabled={operationLoading}
                              style={{ background: 'rgba(0,255,136,0.15)', color: '#00ff88', border: '1px solid rgba(0,255,136,0.3)', padding: '6px 14px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '800', cursor: 'pointer', opacity: operationLoading ? 0.6 : 1 }}
                            >
                              {operationLoading ? 'COMPRANDO...' : 'CONFIRMAR'}
                            </button>
                            <button
                              onClick={() => setConfirmPair(null)}
                              style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-dim)', border: '1px solid rgba(255,255,255,0.1)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '700', cursor: 'pointer' }}
                            >
                              CANCELAR
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => { setConfirmPair(pair); setError(''); setResult(null); }}
                            disabled={!!operationLoading}
                            style={{ background: 'rgba(0,255,136,0.1)', color: '#00ff88', border: '1px solid rgba(0,255,136,0.2)', padding: '6px 16px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '800', cursor: 'pointer', transition: 'all 0.2s' }}
                          >
                            COMPRAR
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          loading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>Cargando posiciones abiertas...</div>
          ) : positions.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>
              <Shield size={40} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
              <p style={{ fontSize: '1rem', fontWeight: '600' }}>No tienes posiciones abiertas</p>
              <p style={{ fontSize: '0.82rem', marginTop: '4px' }}>No hay compras pendientes de venta.</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                    <th style={{ textAlign: 'left', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>PAR</th>
                    <th style={{ textAlign: 'right', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>CANTIDAD</th>
                    <th style={{ textAlign: 'right', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>PRECIO ENTRADA</th>
                    <th style={{ textAlign: 'right', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>INVERTIDO</th>
                    <th style={{ textAlign: 'center', padding: '10px 8px', color: 'var(--text-dim)', fontWeight: '700' }}>ACCIÓN</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.pair} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '12px 8px', fontWeight: '700' }}>{p.pair}<span style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: '2px' }}>Pendiente</span></td>
                      <td style={{ padding: '12px 8px', textAlign: 'right', color: '#00f2ff' }}>{p.amount}</td>
                      <td style={{ padding: '12px 8px', textAlign: 'right' }}>${p.avg_entry_price}</td>
                      <td style={{ padding: '12px 8px', textAlign: 'right', fontWeight: '700', color: '#ffaa00' }}>
                        {p.total_invested !== undefined && p.total_invested !== null ? `$${p.total_invested.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : '—'}
                      </td>
                      <td style={{ padding: '12px 8px', textAlign: 'center' }}>
                        {confirmPair === p.pair ? (
                          <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                            <button
                              onClick={() => handleSell(p.pair)}
                              disabled={operationLoading}
                              style={{ background: 'rgba(255,0,85,0.15)', color: '#ff0055', border: '1px solid rgba(255,0,85,0.3)', padding: '6px 14px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '800', cursor: 'pointer', opacity: operationLoading ? 0.6 : 1 }}
                            >
                              {operationLoading ? 'VENDIENDO...' : 'CONFIRMAR'}
                            </button>
                            <button
                              onClick={() => setConfirmPair(null)}
                              style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-dim)', border: '1px solid rgba(255,255,255,0.1)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '700', cursor: 'pointer' }}
                            >
                              CANCELAR
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => { setConfirmPair(p.pair); setError(''); setResult(null); }}
                            disabled={!!operationLoading}
                            style={{ background: 'rgba(255,85,136,0.1)', color: '#ff5588', border: '1px solid rgba(255,85,136,0.2)', padding: '6px 16px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: '800', cursor: 'pointer', transition: 'all 0.2s' }}
                          >
                            VENDER
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  );
}
