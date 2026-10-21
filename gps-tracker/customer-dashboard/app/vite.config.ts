import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served by the customer container at /customer/ (nginx strips the prefix).
// Built assets go to /static so they don't collide with the classic dashboard's /assets.
export default defineConfig({
  base: '/customer/',
  plugins: [react()],
  build: { assetsDir: 'static', chunkSizeWarningLimit: 2000 },
  server: {
    proxy: { '/api': process.env.VITE_API_PROXY || 'http://localhost:8001' },
  },
});
