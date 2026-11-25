# 東京版 Firebase Analytics 利用状況計測

既存FirebaseプロジェクトのGoogle Analyticsを利用する。経路探索、CloudWatch、
ODPT、Firestoreの処理やAPI契約は変更しない。新規DBは不要。

## カスタムイベント

| イベント | 記録するタイミング | パラメータ |
| --- | --- | --- |
| route_search | POST /route の通信試行 | なし |
| route_detail_view | RouteDetailPage の State 初期化（保存経路も含む） | なし |
| realtime_use | GET /bus/location または /train/location の通信試行 | transport: bus / train |

実際の通信開始時に記録するため、既存の同一未完了リクエスト共有はそのまま。
自動検索、再検索、ナビ中の再探索も route_search に含む。リアルタイムの
自動ポーリング・手動更新・失敗応答を含む。時刻表や鉄道便照合は含めない。
画面上のリアルタイム表示成功やナビ開始そのものを表すイベントではない。
検索内容、座標、住所、便ID、ユーザー名、既存UUIDはカスタムイベントに渡さない。
Firebase Analytics SDK自体の自動収集（アプリインスタンス識別子、端末情報等）は
Googleの仕様に従う。広告ID収集と広告パーソナライズを無効化する設定を追加した。
カスタムイベントは東京 Android/iOS の release のみ。SDK収集の初期値は無効とし、
東京releaseのFirebase初期化後に有効化する。SDKの有効状態は永続化されるため、
同じアプリIDに開発版を上書きする場合、特にiOSでは自動イベントを分離できない
可能性がある。Android debug/profileではネイティブ側でも収集を停止する。
本番Firebaseに開発用ビルドを上書きして自動イベントを検証しない。
初期化完了前に発生したイベントは記録されない。計測の失敗は元の診断を報告し、
その計測を停止する。経路検索の結果を変えたり再試行したりしない。

## リリース前

- Firebase Console の既存プロジェクトで Google Analytics を有効にし、
  東京Android/iOSアプリが正しいプロパティに接続されていることを確認する。
- flutter pub get で依存関係と pubspec.lock を解決し、flutter analyze、
  flutter test、Android/iOSのビルドを実行する。iOSは pod install で
  Podfile.lock を更新・検証し、IDFAなしの依存が使用されていることを確認する。
- Google Playのデータセーフティ、App StoreのApp Privacy、
  プライバシーポリシーと必要な同意の扱いを確認・更新する。
  広告連携・Google Signals・広告向けデータ共有の設定も確認する。
- 次回ストア更新で配信する。バージョン番号、Firebase Console設定、ストア申告、
  本番リリースはこのソース変更に含まない。

## 集計

Firebase Console > Analytics > Events で上記イベントのユーザー数と
イベント数を確認する。日単位はプロパティのタイムゾーンを確認する。
GA4の探索で日付、イベント名、総ユーザー数を用い、route_search と
realtime_use のユーザーセグメントを同期間・同アプリ・同じユーザー指標で比較する。
検索のみ / 両方 / realtimeのみはユーザーセグメントの積集合・差集合で分類する。
リアルタイム利用率は全アクティブユーザーまたは検索ユーザーを分母として
区別する。単純なイベント数の割合は利用者割合にならない。
アプリインスタンス単位の概数であり、再インストールや複数端末で変化する。
過去データは復元されず、新バージョン配信後の計測対象ユーザーに限る。
無料の通常イベント分析で開始し、BigQuery等は追加しない。
