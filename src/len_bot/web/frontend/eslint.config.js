import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
import prettier from 'eslint-config-prettier'
import globals from 'globals'

export default tseslint.config(
  {
    ignores: [
      'node_modules/**',
      // Pages and helpers from the Vuetify panel; each goes away when its replacement lands (docs: work.md M2-M4).
      'src/host/**',
      'src/components/**',
      'src/views/NotFoundView.vue',
      'src/plugins/**',
      'src/App.vue',
      'src/**/*.js',
    ],
  },
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'], sourceType: 'module' },
    },
  },
  {
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // Page and primitive names such as Button or Tabs are single words by design.
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['eslint.config.js', 'vite.config.ts', 'scripts/**'],
    languageOptions: { globals: { ...globals.node } },
  },
  prettier,
)
