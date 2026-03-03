module.exports = {
  roots: ["<rootDir>/flows", "<rootDir>/unit"],
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: "<rootDir>/tsconfig.json" }]
  },
  testEnvironment: "node"
};
