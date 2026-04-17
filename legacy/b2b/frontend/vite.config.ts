import path from "path"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
	plugins: [
		react(),
		tailwindcss(),
	],
	server: { port: 5174 },
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
		},
	},
	esbuild: {
		drop: ['console', 'debugger'],
	},
	build: {
		rollupOptions: {
			output: {
				manualChunks: {
					'vendor-react': ['react', 'react-dom'],
					'vendor-charts': ['recharts'],
					'vendor-i18n': ['i18next', 'react-i18next'],
					'vendor-state': ['zustand', '@tanstack/react-query'],
				},
			},
		},
	},
})
