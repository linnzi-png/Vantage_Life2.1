// Runs once in the Jest parent process before any worker starts, so what it
// sets on process.env reaches every test file and the Babel transform.
//
// NODE_ENV: Jest only defaults it to "test" when it is unset. A machine with
// NODE_ENV=production in its user environment (seen 2026-09-29) makes React
// load its production build under Jest, which has no act(), and every render
// fails with "actImplementation is not a function". Forced here so the suite
// does not depend on anyone's shell.
//
// EXPO_PUBLIC_BACKEND_URL: babel-preset-expo inlines EXPO_PUBLIC_* at
// transform time, so setting it in a setup file that is itself transformed is
// too late; auth.tsx would log an error on every import.
module.exports = async () => {
  process.env.NODE_ENV = 'test';
  process.env.EXPO_PUBLIC_BACKEND_URL = 'http://backend.test';
};
