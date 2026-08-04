import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["build/**"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2021 },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    settings: { react: { version: "detect" } },
    rules: {
      ...react.configs.recommended.rules,
      "react/no-unknown-property": "off",
      "react/react-in-jsx-scope": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "react/prop-types": ["error", { skipUndeclared: true }],
      "react-refresh/only-export-components": "error",
      "react-hooks/rules-of-hooks": "error",
    },
  },
  {
    files: [
      "src/components/ui/badge.tsx",
      "src/components/ui/button-group.tsx",
      "src/components/ui/button.tsx",
      "src/components/ui/combobox.tsx",
      "src/components/ui/tabs.tsx",
      "src/components/ui/toast.tsx",
      "src/components/ui/toggle.tsx",
    ],
    rules: { "react-refresh/only-export-components": "off" },
  },
);
