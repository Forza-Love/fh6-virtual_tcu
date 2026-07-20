import antfu from '@antfu/eslint-config'
import prettier from 'eslint-config-prettier'

export default antfu(
  {
    vue: true,

    stylistic: false,
    formatters: false,

    rules: {
      'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
      '@typescript-eslint/no-explicit-any': 0,
    },

    ignores: [
      '**/dist/',
      '**/out/',
      '**/release/',
      '**/node_modules/',
      'virtual_tcu/',
      '.claude/',
      '.cursor/**',
      '.superpowers/**',
      '.husky/',
      '.vscode/',
      'docs/',
      'CLAUDE.md',
      '**/tsconfig.*.json',
      '**/*.d.ts',
      '**/components.d.ts',
    ],
  },
  {
    files: ['apps/electron/src/main/**/*.ts'],
    rules: {
      'node/prefer-global/process': 'off',
      'node/prefer-global/buffer': 'off',
      'no-console': 'off',
    },
  },
).append(prettier)
