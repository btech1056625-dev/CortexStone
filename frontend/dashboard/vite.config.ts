import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, same-origin proxying avoids CORS (the backend registers no CORS middleware).
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', '').VITE_API_PROXY_TARGET || 'http://localhost:8000';
  return { plugins: [react()], server: { proxy: { '/api': target, '/health': target, '/ready': target } } };
});
