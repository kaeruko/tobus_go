import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as maps;
import 'package:url_launcher_platform_interface/link.dart' as launcher_link;
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart'
    as launcher;
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/logic/transfer_walk_details.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';
import 'package:toeigo/widgets/transfer_walk_sheet.dart';

class FakeTransferMaps extends maps.GoogleMapsFlutterPlatform {
  @override
  Widget buildViewWithConfiguration(
    int creationId,
    void Function(int) onPlatformViewCreated, {
    required maps.MapWidgetConfiguration widgetConfiguration,
    maps.MapConfiguration mapConfiguration = const maps.MapConfiguration(),
    maps.MapObjects mapObjects = const maps.MapObjects(),
  }) => const SizedBox();
}

class FakeTransferLauncher extends launcher.UrlLauncherPlatform {
  @override
  launcher_link.LinkDelegate? get linkDelegate => null;

  final urls = <Uri>[];
  final modes = <launcher.PreferredLaunchMode>[];

  @override
  Future<bool> launchUrl(String url, launcher.LaunchOptions options) async {
    urls.add(Uri.parse(url));
    modes.add(options.mode);
    return true;
  }
}

StopPoint transferStop(String name, String english, double lat, double lon) =>
    StopPoint(name: name, nameEn: english, point: LatLng(lat, lon));

List<StepSeg> buildTransferSteps() => [
  StepSeg(
    stepId: 'arriving',
    kind: 'bus',
    title: '上23 上野松坂屋前行',
    titleEn: 'Ue23 · Ueno-Matsuzakaya',
    departureTime: '11:30',
    arrivalTime: '12:04',
    fromName: '平井七丁目',
    fromNameEn: 'Hirai 7-chome',
    toName: '浅草雷門',
    toNameEn: 'Asakusa-Kaminarimon',
    stops: [
      transferStop('平井七丁目', 'Hirai 7-chome', 35.70, 139.84),
      transferStop('浅草雷門', 'Asakusa-Kaminarimon', 35.710, 139.796),
    ],
  ),
  StepSeg(
    stepId: 'walking',
    kind: 'walk',
    title: '徒歩',
    fromName: '浅草雷門',
    fromNameEn: 'Asakusa-Kaminarimon',
    toName: '浅草雷門南',
    toNameEn: 'Asakusa-Kaminarimon-Minami',
    minutes: 3,
    meters: 210,
  ),
  StepSeg(
    stepId: 'waiting',
    kind: 'wait',
    title: '待ち時間',
    fromName: '浅草雷門南',
    fromNameEn: 'Asakusa-Kaminarimon-Minami',
    toName: '浅草雷門南',
    toNameEn: 'Asakusa-Kaminarimon-Minami',
    place: '浅草雷門南',
    placeEn: 'Asakusa-Kaminarimon-Minami',
    minutes: 4,
    departureTime: '12:07',
    arrivalTime: '12:11',
  ),
  StepSeg(
    stepId: 'departing',
    kind: 'bus',
    title: '草64 池袋駅東口行',
    titleEn: 'Kusa64 · Ikebukuro East Exit',
    fromName: '浅草雷門南',
    fromNameEn: 'Asakusa-Kaminarimon-Minami',
    toName: '池袋駅東口',
    toNameEn: 'Ikebukuro East Exit',
    departureTime: '12:11',
    arrivalTime: '13:11',
    stops: [
      transferStop('浅草雷門南', 'Asakusa-Kaminarimon-Minami', 35.711, 139.795),
      transferStop('池袋駅東口', 'Ikebukuro East Exit', 35.729, 139.712),
    ],
  ),
];

void main() {
  late FakeTransferLauncher urlLauncher;

  setUp(() {
    final oldMaps = maps.GoogleMapsFlutterPlatform.instance;
    final oldLauncher = launcher.UrlLauncherPlatform.instance;
    maps.GoogleMapsFlutterPlatform.instance = FakeTransferMaps();
    urlLauncher = FakeTransferLauncher();
    launcher.UrlLauncherPlatform.instance = urlLauncher;
    addTearDown(() {
      maps.GoogleMapsFlutterPlatform.instance = oldMaps;
      launcher.UrlLauncherPlatform.instance = oldLauncher;
    });
  });

  testWidgets('sheet shows both scheduled clocks, exact stop markers, and walking link',
      (tester) async {
    final steps = buildTransferSteps();
    final transfer = TransferWalkDetails.forStep(steps, 1)!;
    await tester.pumpWidget(CupertinoApp(
      locale: const Locale('ja'),
      home: CupertinoPageScaffold(
        child: Center(
          child: CupertinoButton(
            onPressed: () => showTransferWalkSheet(
              tester.element(find.byType(CupertinoPageScaffold)),
              transfer,
            ),
            child: const Text('乗換を見る'),
          ),
        ),
      ),
    ));

    await tester.tap(find.text('乗換を見る'));
    await tester.pumpAndSettle();

    expect(find.text('乗換案内'), findsOneWidget);
    expect(find.text('A 降車予定'), findsOneWidget);
    expect(find.text('B 乗車予定'), findsOneWidget);
    expect(find.text('12:04'), findsOneWidget);
    expect(find.text('12:11'), findsOneWidget);
    expect(find.textContaining('乗換時間 7分'), findsOneWidget);
    expect(find.textContaining('徒歩 約3分'), findsOneWidget);
    expect(find.textContaining('待ち 約4分'), findsOneWidget);

    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(map.polylines, isEmpty);
    final pins = {for (final marker in map.markers) marker.markerId.value: marker.position};
    expect(pins, {
      'transfer_alight': const LatLng(35.710, 139.796),
      'transfer_board': const LatLng(35.711, 139.795),
    });

    await tester.tap(find.text('Googleマップで徒歩ルートを見る'));
    await tester.pumpAndSettle();

    expect(urlLauncher.urls, hasLength(1));
    expect(urlLauncher.urls.single.path, '/maps/dir/');
    expect(urlLauncher.urls.single.queryParameters, {
      'api': '1',
      'origin': '35.71,139.796',
      'destination': '35.711,139.795',
      'travelmode': 'walking',
    });
    expect(urlLauncher.modes.single,
        launcher.PreferredLaunchMode.externalApplication);
    expect(tester.takeException(), isNull);
  });

  testWidgets('both the walk and waiting cards expose the same transfer tap',
      (tester) async {
    final steps = buildTransferSteps();
    var taps = 0;
    await tester.pumpWidget(CupertinoApp(
      locale: const Locale('ja'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: CupertinoPageScaffold(
        child: ListView(children: [
          RouteStepTile(segment: steps[1], onTransferTap: () => taps++),
          RouteStepTile(segment: steps[2], onTransferTap: () => taps++),
        ]),
      ),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('徒歩'));
    await tester.pump();
    await tester.tap(find.text('待ち時間'));
    await tester.pump();
    expect(taps, 2);
    expect(tester.takeException(), isNull);
  });
}
