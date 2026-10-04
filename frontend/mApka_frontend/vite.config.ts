// vite.config.ts
import { defineConfig } from 'vite'        // narzędzie do typowania konfiguracji
import react from '@vitejs/plugin-react'   // wtyczka obsługująca Reacta
import tailwindcss from '@tailwindcss/vite'// wtyczka Tailwind v4

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),   // <- Tailwind działa teraz "wewnątrz" Vite, bez plików konfiguracyjnych
  ],
})