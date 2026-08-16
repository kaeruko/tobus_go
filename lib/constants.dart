// flutter run ではローカルAPIを既定値として使う。
// ストア向けAABでは scripts/build_aab.ps1 が API_BASE を明示する。
const String kApiBase = String.fromEnvironment(
  'API_BASE',
  defaultValue: 'http://127.0.0.1:8000',
);
