import baseConfig from "./cfg/eslint.config.js";

export default [
  ...baseConfig,
  {
    files: ["tests/mockdata/clean-tracks.json"],
    rules: {
      "json/no-unsafe-values": "off",
    },
  },
];
