# toeigo

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Lab: Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Cookbook: Useful Flutter samples](https://docs.flutter.dev/cookbook)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## 経路検索の「所要時間優先」モードについて

フロントエンドの UI では「時間短い優先」に対応する値として `shortTime` を利用していますが、バックエンドの探索エンジンが受け付ける最短時間モードは `time`（`fast` と同義）です。

そのため API 呼び出し時には以下のように値をマッピングしています。

- `shortTime` → `time`（最短時間探索）
- 未指定または不明な値 → `cost`（デフォルトの探索）

バックエンド側でも `shortTime`/`fast` を `time` として正規化するフォールバックを入れており、古いクライアントからでも最短時間探索が実行されます。
