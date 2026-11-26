import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/test_banner_policy.dart';
import 'package:toeigo/widgets/test_route_banner.dart';

void main() {
  testWidgets('banner hides when a parent consumes the keyboard inset', (
    tester,
  ) async {
    const banner = Key('sample-banner');
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpWidget(
      CupertinoApp(
        home: Builder(
          builder: (context) => MediaQuery.removeViewInsets(
            context: context,
            removeBottom: true,
            child: const RouteBannerSlot(child: SizedBox(key: banner)),
          ),
        ),
      ),
    );
    expect(find.byKey(banner), findsOneWidget);

    tester.view.viewInsets = const FakeViewPadding(bottom: 280);
    await tester.pump();
    expect(find.byKey(banner), findsNothing);

    tester.view.resetViewInsets();
    await tester.pump();
    expect(find.byKey(banner), findsOneWidget);
  });

  String? unit({
    bool debug = true,
    bool requested = true,
    bool web = false,
    TargetPlatform platform = TargetPlatform.android,
    String city = 'tokyo',
  }) => testBannerUnitId(
    debug: debug,
    requested: requested,
    web: web,
    platform: platform,
    cityKey: city,
  );

  test('only explicitly opted-in Tokyo mobile debug builds use sample units', () {
    expect(unit(), 'ca-app-pub-3940256099942544/6300978111');
    expect(unit(platform: TargetPlatform.iOS),
        'ca-app-pub-3940256099942544/2934735716');
    expect(unit(debug: false), isNull);
    expect(unit(requested: false), isNull);
    expect(unit(web: true), isNull);
    expect(unit(city: 'sendai'), isNull);
    expect(unit(platform: TargetPlatform.windows), isNull);
    expect(unit(platform: TargetPlatform.macOS), isNull);
    expect(unit(platform: TargetPlatform.linux), isNull);
    expect(unit(platform: TargetPlatform.fuchsia), isNull);
  });

  test('publisher units require explicit Tokyo mobile release opt-in', () {
    String? production({
      bool release = true,
      bool requested = true,
      bool web = false,
      TargetPlatform platform = TargetPlatform.android,
      String city = 'tokyo',
    }) => productionBannerUnitId(
      release: release,
      requested: requested,
      web: web,
      platform: platform,
      cityKey: city,
    );

    expect(production(), 'ca-app-pub-1701253412237513/5953725636');
    expect(production(platform: TargetPlatform.iOS),
        'ca-app-pub-1701253412237513/2050652992');
    expect(production(release: false), isNull);
    expect(production(requested: false), isNull);
    expect(production(web: true), isNull);
    expect(production(city: 'sendai'), isNull);
    for (final platform in [
      TargetPlatform.windows, TargetPlatform.macOS,
      TargetPlatform.linux, TargetPlatform.fuchsia,
    ]) {
      expect(production(platform: platform), isNull);
    }
    expect(configuredProductionBannerUnitId('tokyo'), isNull);
  });
}
