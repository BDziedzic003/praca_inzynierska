// Konfiguracja Vite. Podczas pracy (npm run dev) zapytania do serwera robota
// są przekazywane do serwer.py działającego na tym samym komputerze.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const SERWER = 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': SERWER,
      '/stream': SERWER,
      '/snapshot': SERWER,
      '/ws': { target: SERWER, ws: true },
    },
  },
});
