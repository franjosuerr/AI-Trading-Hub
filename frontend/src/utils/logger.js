import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

const remoteLog = async (level, message, context = {}) => {
    try {
        const token = localStorage.getItem('auth_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        await axios.post(`${API_BASE}/logs/`, {
            level,
            message,
            context
        }, { headers });
    } catch (error) {
        // Silenciar errores de auth para no spammear la consola
        if (error.response?.status !== 401) {
            console.error("Failed to send log to server:", error);
        }
    }
};

const logger = {
    info: (msg, context = {}) => {
        console.log(`%c[INFO] ${msg}`, 'color: #00f2ff; font-weight: bold;', context);
        remoteLog('info', msg, context);
    },
    warn: (msg, context = {}) => {
        console.warn(`[WARN] ${msg}`, context);
        remoteLog('warning', msg, context);
    },
    error: (msg, context = {}) => {
        console.error(`[ERROR] ${msg}`, context);
        remoteLog('error', msg, context);
    }
};

export default logger;
