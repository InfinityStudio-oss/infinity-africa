// Expo's own flat config. Kept separate from the web app's
// eslint-config-next: the two lint different platforms and share no rules.
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*"],
  },
]);
