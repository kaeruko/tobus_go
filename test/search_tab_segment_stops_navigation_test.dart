import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show BottomNavigationBarItem;
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/segment_stops_page.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

class _RootPopObserver extends NavigatorObserver {
  int popCount = 0;

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    popCount += 1;
    super.didPop(route, previousRoute);
  }
}

class _SearchResultsPage extends StatelessWidget {
  final StepSeg segment;

  const _SearchResultsPage({required this.segment});

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('検索結果')),
      child: SafeArea(
        child: Center(
          child: CupertinoButton(
            key: const ValueKey('open-route-detail'),
            onPressed: () {
              Navigator.of(context).push(
                CupertinoPageRoute<void>(
                  builder: (_) => _RouteDetailHarness(segment: segment),
                ),
              );
            },
            child: const Text('路線詳細を開く'),
          ),
        ),
      ),
    );
  }
}

class _RouteDetailHarness extends StatelessWidget {
  final StepSeg segment;

  const _RouteDetailHarness({required this.segment});

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('路線詳細')),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [RouteStepTile(segment: segment)],
        ),
      ),
    );
  }
}

void main() {
  StepSeg busSegment() => StepSeg(
    stepId: 'search-route-bus-1',
    kind: 'bus',
    title: '里22 日暮里駅前行',
    fromName: '亀戸駅前',
    toName: '日暮里駅前',
    minutes: 24,
    edges: 2,
    stops: [
      StopPoint(
        name: '亀戸駅前',
        point: const LatLng(35.6973, 139.8262),
        isOrigin: true,
      ),
      StopPoint(
        name: '日暮里駅前',
        point: const LatLng(35.7278, 139.7709),
        isDestination: true,
      ),
    ],
  );

  testWidgets(
    'search tab keeps route detail and stops on nested Navigator and back never pops root',
    (tester) async {
      final rootObserver = _RootPopObserver();
      final searchNavigatorKey = GlobalKey<NavigatorState>();
      final segment = busSegment();

      await tester.pumpWidget(
        CupertinoApp(
          navigatorObservers: [rootObserver],
          home: CupertinoTabScaffold(
            tabBar: CupertinoTabBar(
              items: const [
                BottomNavigationBarItem(
                  icon: Icon(CupertinoIcons.search),
                  label: '検索',
                ),
                BottomNavigationBarItem(
                  icon: Icon(CupertinoIcons.settings),
                  label: '設定',
                ),
              ],
            ),
            tabBuilder: (context, index) {
              if (index == 0) {
                return CupertinoTabView(
                  navigatorKey: searchNavigatorKey,
                  builder: (_) => _SearchResultsPage(segment: segment),
                );
              }
              return CupertinoTabView(
                builder: (_) => const CupertinoPageScaffold(
                  child: Center(child: Text('設定')),
                ),
              );
            },
          ),
        ),
      );

      expect(searchNavigatorKey.currentState, isNotNull);
      expect(searchNavigatorKey.currentState!.canPop(), isFalse);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byKey(const ValueKey('open-route-detail')));
      await tester.pumpAndSettle();

      expect(find.text('路線詳細'), findsOneWidget);
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.text('里22 日暮里駅前行'));
      await tester.pumpAndSettle();

      expect(find.text('亀戸駅前'), findsOneWidget);
      expect(find.text('日暮里駅前'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('segment-stops-back')),
        findsOneWidget,
      );
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byKey(const ValueKey('segment-stops-back')));
      await tester.pumpAndSettle();

      expect(find.text('路線詳細'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('segment-stops-back')),
        findsNothing,
      );
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byType(CupertinoNavigationBarBackButton));
      await tester.pumpAndSettle();

      expect(find.text('検索結果'), findsOneWidget);
      expect(searchNavigatorKey.currentState!.canPop(), isFalse);
      expect(rootObserver.popCount, 0);
    },
  );

  testWidgets('stops back fails fast when no previous app route exists', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(home: SegmentStopsPage(segment: busSegment())),
    );

    await tester.tap(find.byKey(const ValueKey('segment-stops-back')));
    await tester.pump();

    expect(tester.takeException(), isA<StateError>());
  });
}
