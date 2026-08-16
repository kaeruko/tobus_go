import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/widgets/trip_schedule_window_card.dart';

void main() {
  testWidgets('listTilesはSoloの件数表示とride tapを保つ', (tester) async {
    final entry = ScheduleEntry(
      id: 'ride-1',
      plannedAt: DateTime(2026, 8, 16, 9, 42),
      label: '浅草線に乗車',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'step-rail-1',
    );
    String? tappedEntryId;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TripScheduleWindowCard(
            title: '今回の経路',
            resolvedEntry: entry,
            entries: [entry],
            completedCount: 2,
            totalCount: 7,
            activeLabel: '乗車中',
            counterLabelBuilder: (completedCount, totalCount) =>
                '$completedCount / $totalCount ステップ',
            appearance: TripScheduleWindowAppearance.listTiles,
            onTapEntry: (value) => tappedEntryId = value.id,
          ),
        ),
      ),
    );

    expect(find.text('今回の経路'), findsOneWidget);
    expect(find.text('2 / 7 ステップ'), findsOneWidget);
    expect(find.text('乗車中'), findsOneWidget);
    expect(find.text('09:42'), findsOneWidget);

    await tester.tap(find.text('浅草線に乗車'));
    await tester.pump();
    expect(tappedEntryId, 'ride-1');
  });

  testWidgets('boxedRowsは別instanceでもentry idでactive判定する', (tester) async {
    final entry = ScheduleEntry(
      id: 'manual-1',
      plannedAt: DateTime(2026, 8, 16, 10, 15),
      label: '休憩',
      description: '公園で休憩',
      itemKind: ScheduleEntryKind.event,
    );
    final resolvedCopy = ScheduleEntry(
      id: 'manual-1',
      plannedAt: entry.plannedAt,
      label: entry.label,
      description: entry.description,
      itemKind: entry.itemKind,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TripScheduleWindowCard(
            title: '今日の予定',
            resolvedEntry: resolvedCopy,
            entries: [entry],
            completedCount: 3,
            activeLabel: 'いまここ',
            counterLabelBuilder: (completedCount, totalCount) =>
                '完了 $completedCount 件',
            appearance: TripScheduleWindowAppearance.boxedRows,
            emptyLabel: 'すべての予定を完了しました。',
          ),
        ),
      ),
    );

    expect(find.text('今日の予定'), findsOneWidget);
    expect(find.text('完了 3 件'), findsOneWidget);
    expect(find.text('いまここ'), findsOneWidget);
    expect(find.text('公園で休憩'), findsOneWidget);
  });

  testWidgets('boxedRowsは予定が空ならemptyLabelを表示する', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TripScheduleWindowCard(
            title: '今日の予定',
            resolvedEntry: null,
            entries: const [],
            completedCount: 5,
            activeLabel: '移動中',
            counterLabelBuilder: (completedCount, totalCount) =>
                '完了 $completedCount 件',
            appearance: TripScheduleWindowAppearance.boxedRows,
            emptyLabel: 'すべての予定を完了しました。',
          ),
        ),
      ),
    );

    expect(find.text('すべての予定を完了しました。'), findsOneWidget);
  });
}
