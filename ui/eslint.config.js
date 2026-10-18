// @ts-check
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/** Any import that reaches the thesis-only folder, however it is written. */
const THESIS = {
  group: ["**/thesis", "**/thesis/**", "./thesis", "./thesis/**"],
  message: "Product code never imports the thesis-only views.",
};

export default tseslint.config(
  { ignores: ["dist", "node_modules", "test-results", "playwright-report", "scripts"] },
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // `any` only where a comment names the boundary it crosses.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    // The product never imports the thesis-only views: they live in src/thesis/, which the
    // product can ship without.
    files: ["src/**"],
    ignores: ["src/thesis/**"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [THESIS] }],
    },
  },
  {
    // The shell renders the groups and whatever the view registry lists; it never imports a
    // view itself, so a later view arrives by one registry line and never edits the shell.
    files: ["src/shell/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            THESIS,
            { group: ["../views/*/**"], message: "The shell reads views from the registry only." },
          ],
        },
      ],
    },
  },
  {
    files: ["eslint.config.js"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
