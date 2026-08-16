# Solo / Group 移動中ナビゲーション共通化設計

## 目的

Solo と Group で移動中ナビゲーションの実装が分岐し、片方だけ修正される事故を減らす。

特に次の領域は Solo / Group の製品上の違いではなく、同じ移動を観測・表示する共通機能として扱う。

- 現在の schedule step 解決
- バス / 鉄道 Realtime ポーリング
- 乗車中 / 接近中 / 到着の進捗
- 最後に確定した駅・停留所
- 遅延 / 乗換え成立判定
- Replan anchor / replan request
- 現在の移動状況カード
- 現在前後の schedule 表示
- 停留所 / 駅一覧への遷移

Solo を基底 class にして Group が `extends` する構造にはしない。Solo と Group は「親子」ではなく、共通ナビゲーションに異なる権限・操作を差し込む兄弟として扱う。

## 現状

### すでに共通化されているもの

`MemberModeController` / `memberUiStateProvider` は Solo と Group member の両方で利用されており、Realtime 取得とナビ進捗の中心はすでに共有されている。

共通ドメイン / Provider も増えている。

- `TripCoordinator`
- `TripNavigator`
- `memberNavProgressProvider`
- `resolvedDelayImpactProvider`
- `replanAnchorProvider`
- `currentRouteReplanRequestProvider`
- `RouteReplanPresentation`
- `TripNavigationStatusCard`
- `DelayRecoveryCard`
- `SegmentStopsPage`

この層は今後も Solo / Group を分岐させない。

### まだ重複しているもの

`SoloTripView` と `MemberModePage` は、共通 Provider を利用しているにもかかわらず、Scaffold 以降を別々に組み立てている。

代表的な重複:

- navState の背景色
- `TripNavigationStatusCard`
- Realtime 更新ボタン
- Fake bus debug ボタン
- delay card 周辺
- schedule window の表示
- ride step の stops を開く処理
- loading / provider error の画面

このため「Solo は直したが Group は残った」のような差分が発生しやすい。

## 設計方針

### 継承ではなく composition

避ける形:

```dart
class GroupTripPage extends SoloTripPage {
  // 大量の override
}
```

Solo 固有の lifecycle と Group 固有の権限は対称ではないため、継承すると override が増え、親 class の変更が Group の暗黙仕様になる。

採用する形:

```text
                  shared logic/providers
                         │
              ActiveTripNavigationView
                 /        |        \
              Solo    GroupMember  GroupLeader
             wrapper     wrapper      wrapper
```

共通 View は移動中ナビゲーションの骨格だけを所有し、各モード固有操作は slot / policy として注入する。

## 目標構成

### 1. 共通ロジック層

既存の `MemberModeController` を当面そのまま共有する。

名称は将来 `ActiveTripNavigationController` へ変更可能だが、名称変更だけの大規模 diff は最初の移行では行わない。

共通層が責任を持つもの:

```text
Trip stream
  ↓
TripCoordinator
  ↓
MemberModeController
  ├─ BusLocationSource
  ├─ TrainLocationSource
  ├─ ReplanTransitMemory
  └─ memberNavProgressProvider
  ↓
MemberUiState
  ├─ navState
  ├─ resolvedEntry
  ├─ windowEntries
  ├─ completedCount
  └─ activeLabel
```

ここに Solo / Group 条件を追加しない。

### 2. 共通 presentation 層

新規:

```text
lib/widgets/active_trip_navigation_view.dart
lib/widgets/trip_schedule_window_card.dart
```

#### `ActiveTripNavigationView`

役割:

- 共通 Scaffold
- navState による背景色
- `TripNavigationStatusCard`
- 共通の spacing / scroll
- 共通 warning section の配置
- schedule window の配置
- 共通 stops open callback
- mode 固有 section の slot
- mode 固有 bottom action の slot

概念 API:

```dart
class ActiveTripNavigationView extends StatelessWidget {
  final Trip trip;
  final MemberUiState uiState;
  final PreferredSizeWidget appBar;

  final Widget? delaySection;
  final List<Widget> extraSections;
  final Widget scheduleSection;
  final List<Widget> afterScheduleSections;
  final Widget? bottomNavigationBar;

  final VoidCallback onTapStops;
}
```

重要: この Widget 自体は Solo / Group / leader を判定しない。

`trip.type == ...` のような分岐を共通 Widget の中へ入れない。差分は呼び出し側で組み立てる。

#### `TripScheduleWindowCard`

Solo の `_SoloScheduleCard` と Group member の `_SchedulePeek` を統合する。

データは共通:

```dart
resolvedEntry
windowEntries
completedCount
activeLabel
```

表示差分は設定で渡す。

概念 API:

```dart
class TripScheduleWindowCard extends StatelessWidget {
  final String title;
  final String Function(int completedCount, int totalCount) counterLabelBuilder;
  final ScheduleEntry? resolvedEntry;
  final List<ScheduleEntry> entries;
  final int completedCount;
  final int? totalCount;
  final String activeLabel;
  final ValueChanged<ScheduleEntry>? onTapEntry;
  final TripScheduleWindowStyle style;
}
```

Solo:

```text
title = 今回の経路
counter = 1 / 7 ステップ
ride tap = stops を開く
```

Group member:

```text
title = 今日の予定
counter = 完了 1 件
ride tap = stops を開く
```

「データ解決」と「見た目」を分離し、Group 用 schedule データを Solo 用へ変換しない。

### 3. mode policy

権限差を Widget 継承で表さず、明示的な policy と callback で表す。

新規候補:

```text
lib/logic/active_trip_navigation_policy.dart
```

```dart
enum ActiveTripNavigationRole {
  solo,
  groupMember,
  groupLeader,
}

class ActiveTripNavigationPolicy {
  final ActiveTripNavigationRole role;

  bool get canCommitRouteReplan;
  bool get canCancelTrip;
  bool get canSendSos;
  bool get canLeaveGroup;
  bool get canShiftManualSchedule;
  bool get canCompleteGroupLeg;
}
```

ただし policy は「許可判定の唯一のセキュリティ境界」にはしない。

Firestore transaction / commit service で行っている leader 検証は必ず残す。UI policy は表示・操作可否の presentation 用であり、server state の権限検証を置き換えない。

## モード別責任

### Solo wrapper

`SoloTripView` に残すもの:

- Solo trip の ProviderScope / trip stream override
- Solo の自動完了判定
- `completeTrip`
- `cancelTrip`
- `SoloTripDetailPage`
- Solo の `RouteReplanPreviewButton`
- completed / cancelled の終端画面

共通 View へ移すもの:

- active navigation scaffold
- status card
- common refresh action helper
- schedule window card
- stops navigation
- warning placement

### Group member wrapper

`MemberModePage` に残すもの:

- SOS
- member mode 退出
- GroupDetailPage
- Settings
- read-only group schedule warning
- leader に変更依頼する文言

共通 View へ移すもの:

- status card
- refresh / fake bus common action
- schedule window
- stops navigation
- delay warning placement

### Group leader

`LeaderModePage` 全体を Solo の共通 View に入れない。

現状の `LeaderModePage` は主に「おでかけ編集 / 開始 / 参加者 / 帰り時刻変更 / leg 完了」の管理画面であり、移動中ナビとは責任が違う。

長期的には Group leader の `TravelPhase.active` のときだけ、member と同じ ActiveTripNavigationView を利用する専用 wrapper を用意する。

候補:

```text
GroupLeaderActiveTripPage
```

leader 固有 slot:

- route replan commit
- group manual schedule shift
- leg 完了
- trip 完了
- GroupDetail / SchedulePage への管理導線

planning 中は従来の `LeaderModePage` を編集画面として残す。

最終的な責務:

```text
LeaderModePage
  └─ planning / edit

GroupLeaderActiveTripPage
  └─ active navigation + leader actions
```

これにより Group leader だけ別のナビ進捗実装を持つことを防ぐ。

## 共通化しないもの

以下は無理に共通化しない。

- Solo auto-completion lifecycle
- Group member SOS
- Group join / leave session
- Group leader participant management
- Group leader manual schedule editing
- Group leader leg completion
- Solo cancel と Group cancel の確認文言・影響範囲
- Group schedule impact の編集 action

共通化の目的は行数削減ではなく「同じ意味の機能が二重実装されないこと」とする。

## データ / 安全性 invariant

共通化中も次を変えない。

1. GPS を replan origin に使わない。
2. Realtime が不明な onboard 状態では前の駅・停留所へ fallback しない。
3. stale ETA を `now` へ丸めない。
4. fixed transit の時刻を `shiftToStart` で偽造しない。
5. Group route commit は leader のみ。
6. Group member は route / manual schedule を書き換えない。
7. `MemberModeController` の bus / rail 判定を mode ごとに複製しない。
8. `resolvedDelayImpactProvider` / `replanAnchorProvider` を mode 固有実装へ fork しない。

## 移行手順

一度に画面を作り直さない。

### Phase 1: 純粋 UI 部品

- `_SoloScheduleCard` と `_SchedulePeek` を `TripScheduleWindowCard` に統合
- stops を開く共通 helper を利用 / 整理
- Fake bus / refresh action を小さい共通 Widget または helper にする

ここでは画面構造を変えない。

### Phase 2: 共通 body

`ActiveTripNavigationView` を追加し、まず Solo と Group member の body を載せ替える。

差分は slot で注入する。

Golden test / widget test で次を固定する。

- Solo: delay action を表示可能
- Group member: 同じ delay 内容だが commit action なし
- Solo: Group schedule warning なし
- Group member: Group schedule warning あり

### Phase 3: common presentation model

画面側で複数 Provider を個別に組み合わせる量が増える場合だけ、read-only model を追加する。

候補:

```dart
class ActiveTripNavigationPresentationState {
  final Trip trip;
  final MemberUiState uiState;
  final DelayImpactResolution delay;
  final GroupScheduleImpact? groupScheduleImpact;
}
```

Group 専用値を Solo でダミー生成しない。optional の意味を明確にする。

### Phase 4: Group leader active navigation

`TravelPhase.active` の leader を `GroupLeaderActiveTripPage` へ導く。

- MemberModeController を共有
- ActiveTripNavigationView を共有
- leader action だけ追加
- planning/edit は LeaderModePage に残す

この Phase は UI 導線変更を含むため、Phase 1〜3 と分離する。

### Phase 5: 命名整理

共通化が安定してから必要なら:

```text
MemberModeController -> ActiveTripNavigationController
MemberUiState        -> ActiveTripNavigationState
```

へ rename する。

rename は挙動変更 PR と混ぜない。

## テスト方針

### logic / provider

同一 test を role 別に複製しない。

Realtime / navigation / delay / replan anchor は shared test 1系統を維持する。

### Widget

共通 View に対して slot の契約を確認する。

最低限:

- common status card が同じ navState を表示
- schedule active row が同じ resolvedEntry を使う
- onTapStops が ride のみ発火
- Solo action が Group member へ漏れない
- Group member SOS / leave が Solo へ漏れない
- Group leader action が member へ漏れない

### regression

今回の共通化で特に防ぎたい regression:

- Solo だけ「経路を見直す」が消え、Group に残る
- Solo だけ stale Realtime guard が効く
- Group だけ残り駅 / 停留所表示が古い
- Group member に route commit UI が出る

## 完了条件

次を満たしたら「Solo / Group ナビ共通化」は完了とする。

- Realtime / progress / delay / replan のロジック実装が1系統
- Solo と Group member の active body が `ActiveTripNavigationView` を利用
- schedule window が共通 Widget
- stops navigation が共通 helper / component
- mode 差分は wrapper / slot / policy に限定
- Group leader active navigation も同じ controller/view を利用
- planning/edit 用 LeaderModePage は独立維持
- CI の Flutter analyze / tests が成功

## 実装順の推奨

最初の実装 PR は `TripScheduleWindowCard` の抽出だけにする。

理由:

- 変更範囲が小さい
- Solo / Group の表示差を parameter として整理できる
- Provider / lifecycle に触れない
- その後 `ActiveTripNavigationView` へ載せ替えるための境界が見える

この共通化では「Solo を親にする」のではなく、「Solo と Group が同じ active navigation substrate を使う」状態を目標にする。
