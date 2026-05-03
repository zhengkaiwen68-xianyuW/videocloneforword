import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'vue',
              test: /node_modules[\\/](vue|vue-router|pinia)[\\/]/,
              priority: 3
            },
            {
              name: 'element',
              test: /node_modules[\\/](element-plus|@element-plus)[\\/]/,
              priority: 2
            },
            {
              name: 'vendor',
              test: /node_modules[\\/]/,
              priority: 1
            }
          ]
        }
      }
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
