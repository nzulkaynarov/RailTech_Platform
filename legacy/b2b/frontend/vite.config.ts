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
					'vendor-react': ['react', 'react-dom', 'react-router-dom'],
					'vendor-charts': ['recharts'],
					'vendor-i18n': ['i18next', 'react-i18next'],
					'vendor-state': ['zustand', '@tanstack/react-query'],
					'vendor-radix': [
						'@radix-ui/react-dialog',
						'@radix-ui/react-dropdown-menu',
						'@radix-ui/react-popover',
						'@radix-ui/react-select',
						'@radix-ui/react-tabs',
						'@radix-ui/react-tooltip',
						'@radix-ui/react-scroll-area',
						'@radix-ui/react-separator',
						'@radix-ui/react-switch',
						'@radix-ui/react-checkbox',
						'@radix-ui/react-label',
						'@radix-ui/react-slot',
					],
					'vendor-http': ['axios'],
				},
			},
		},
	},
})
