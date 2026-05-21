/** @type {import('eslint').Linter.Config} */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: {
    react: { version: 'detect' },
  },
  plugins: [
    '@typescript-eslint',
    'react',
    'react-hooks',
    'local-rules',
  ],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  rules: {
    // -----------------------------------------------------------------------
    // Custom local rules
    // -----------------------------------------------------------------------

    // Prevent mirroring isPending/isLoading into useState — causes race conditions
    // with TanStack Query v5 because isPending transitions asynchronously.
    'local-rules/no-mirror-query-state': 'error',

    // -----------------------------------------------------------------------
    // TypeScript
    // -----------------------------------------------------------------------
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],

    // -----------------------------------------------------------------------
    // React
    // -----------------------------------------------------------------------
    'react/react-in-jsx-scope': 'off', // not needed with React 17+ JSX transform
    'react/prop-types': 'off',         // TypeScript handles this
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',
  },
}
