// Real normal /route, reviewed original GTFS, common Candidate/card/detail.
// Places upstream responses are fixed by the CI server. The Maps platform
// surface below tests the existing picker callback/confirmation contract only;
// it does NOT certify live Google map tiles, hit testing or geocoding accuracy.
import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart' as maps;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/pages/home_page.dart';
import 'package:toeigo/pages/map_picker_page.dart';
import 'package:toeigo/pages/route_detail_page.dart';
import 'package:toeigo/providers/route_search_provider.dart';
import 'package:toeigo/widgets/route_card.dart';
import 'package:toeigo/widgets/place_field.dart';

class _MapSurface extends maps.GoogleMapsFlutterPlatform {
  final VoidCallback select;
  _MapSurface(this.select);
  @override
  Widget buildViewWithConfiguration(int id, void Function(int) created, {
    required maps.MapWidgetConfiguration widgetConfiguration,
    maps.MapConfiguration mapConfiguration = const maps.MapConfiguration(),
    maps.MapObjects mapObjects = const maps.MapObjects(),
  }) => GestureDetector(key: const Key('ci-maps-render-surface'),
    behavior: HitTestBehavior.opaque, onLongPress: select,
    child: const ColoredBox(color: CupertinoColors.systemGrey5,
      child: Center(child: Text('CI map surface / live Maps SDK unverified'))));
}

String _stage = 'start';

Future<void> _reveal(WidgetTester tester, Finder target) async {
  final scroll = find.descendant(of: find.byType(CustomScrollView).first,
      matching: find.byType(Scrollable)).first;
  tester.state<ScrollableState>(scroll).position.jumpTo(0);
  await tester.pump();
  await tester.scrollUntilVisible(target, 220, scrollable: scroll, maxScrolls: 30);
  await Scrollable.ensureVisible(tester.element(target), alignment: .4);
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> _wait(WidgetTester tester, bool Function() done,
    {String Function()? diagnostic}) async {
  for (var i=0;i<200;i++) {
    if (done()) return;
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
  throw StateError('bounded wait expired at $_stage; ${diagnostic?.call() ?? ""}');
}

Future<void> _place(WidgetTester tester, String role, String query) async {
  _stage = '$role Places query $query';
  final field = find.descendant(of: find.byKey(Key('route-$role')),
      matching: find.byType(CupertinoTextField));
  await _reveal(tester, field);
  // After a picker route is popped, explicitly perform the user's field tap
  // and finish focus restoration before sending text through TestTextInput.
  // Sending only enterText previously left this field empty and unfocused;
  // no autocomplete request was sent. Never bypass the field via provider.
  await tester.tap(field);
  await tester.pumpAndSettle();
  final editable = find.descendant(of:field, matching:find.byType(EditableText));
  expect(tester.widget<EditableText>(editable).focusNode.hasFocus,isTrue,
      reason:'$_stage: the actual input tap must acquire focus');
  await tester.enterText(field, query);
  expect(tester.widget<CupertinoTextField>(field).controller!.text,query,
      reason:'$_stage: preserve the declared query at the input boundary');
  final prediction = find.widgetWithText(CupertinoButton, query);
  await _wait(tester, () => prediction.evaluate().isNotEmpty, diagnostic: () {
    final input=tester.widget<CupertinoTextField>(field);
    final editable=tester.widget<EditableText>(find.descendant(of:field,
        matching:find.byType(EditableText)));
    final place=tester.widget<PlaceField>(find.byKey(Key('route-$role')));
    final labels=find.descendant(of:find.byKey(Key('route-$role')),
        matching:find.byType(Text)).evaluate()
        .map((e)=>(e.widget as Text).data).toList();
    return 'controller=${input.controller!.value}; focus=${editable.focusNode.hasFocus}; '
        'value=${place.value}; display=${place.displayValue}; labels=$labels';
  });
  await tester.ensureVisible(prediction);
  await tester.tap(prediction);
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Normal Sendai Places -> real route -> card -> detail and picker contract', (tester) async {
    final container = ProviderContainer();
    final oldMaps = maps.GoogleMapsFlutterPlatform.instance;
    const selectedPoint = LatLng(38.22439,140.87613);
    maps.GoogleMapsFlutterPlatform.instance = _MapSurface(() {
      final map = tester.widget<GoogleMap>(find.byType(GoogleMap).last);
      map.onLongPress?.call(selectedPoint);
    });
    addTearDown(() {maps.GoogleMapsFlutterPlatform.instance=oldMaps;container.dispose();});
    try {
      expect(configuredCityKey,'sendai');expect(sendaiCoordinateDevelopment,isTrue);
      configureApiBase(Uri.parse(const String.fromEnvironment('API_BASE')));
      ApiClient.resetWarmUpForTesting();
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('farePolicyId:sendai:reviewed-coordinate-development');
      final notifier=container.read(routeSearchProvider.notifier);
      notifier.setStartTime(DateTime(2026,11,19,9));
      await tester.pumpWidget(UncontrolledProviderScope(container:container,
        child:CupertinoApp(locale:const Locale('ja'),
          localizationsDelegates:AppLocalizations.localizationsDelegates,
          supportedLocales:AppLocalizations.supportedLocales,
          home:const RouteSearchPage(title:'仙台でGO'))));
      await tester.pump(const Duration(milliseconds:500));
      _stage='select actual existing fare settings';
      await _reveal(tester,find.byKey(const Key('sendai-coordinate-fare-settings')));
      await tester.tap(find.byKey(const Key('sendai-coordinate-fare-settings')));
      await _wait(tester,()=>find.text('ふれあい乗車証（本人所持・開発検証用）').evaluate().isNotEmpty);
      await tester.tap(find.text('ふれあい乗車証（本人所持・開発検証用）'));
      await _wait(tester,()=>prefs.getString('farePolicyId:sendai:reviewed-coordinate-development')=='sendai_fureai_pass');
      final navigator=tester.state<NavigatorState>(find.byType(Navigator).first);
      navigator.pop();await tester.pumpAndSettle();
      // Set the same date/time as the independently frozen cases. No endpoint,
      // service/date, expected arrival or routing response is changed by CI.
      final cases = [
        ['附属小学校前','市営バス東仙台営業所前','09:38','bus'],
        ['霞の目','泉中央駅','11:06','bus,rail'],
        ['仙台駅前','泉岳自然ふれあい館','10:48','rail,bus'],
        ['霞の目','芦口小学校前','11:07','bus,rail,bus'],
      ];
      for (var index=0;index<cases.length;index++) {
        final c=cases[index];
        notifier.setFrom('');notifier.setTo('');
        notifier.setStartTime(DateTime(2026,11,19,9));
        notifier.setBusOnly(index==0);
        notifier.setPref('shortTime');
        await tester.pump();
        await _place(tester,'origin',c[0]);
        await _wait(tester,()=>container.read(routeSearchProvider).from.isNotEmpty);
        await _place(tester,'destination',c[1]);
        await _wait(tester,()=>container.read(routeSearchProvider).to.isNotEmpty);
        if(index==0) {
          _stage='explicit pass without model consent is rejected';
          await _reveal(tester,find.byKey(const Key('route-search-submit')));
          await tester.tap(find.byKey(const Key('route-search-submit')));
          await _wait(tester,()=>!container.read(routeSearchProvider).isLoading);
          expect(container.read(routeSearchProvider).errorMessage,contains('consent'));
          await _reveal(tester,find.byKey(const Key('sendai-coordinate-consent')));
          await tester.tap(find.byKey(const Key('sendai-coordinate-consent')));
          await tester.pump();
        }
        _stage='normal /route ${c[0]} -> ${c[1]}';
        await _reveal(tester,find.byKey(const Key('route-search-submit')));
        await tester.tap(find.byKey(const Key('route-search-submit')));
        await _wait(tester,()=>!container.read(routeSearchProvider).isLoading);
        final state=container.read(routeSearchProvider);
        expect(state.errorMessage,isNull);expect(state.candidates,isNotEmpty);
        final candidate=state.candidates.first;
        expect(candidate.arrivalTime,c[2]);
        expect(candidate.steps.where((s)=>s.isRide).map((s)=>s.kind).join(','),c[3]);
        expect(candidate.planningJourney,isNotNull);
        expect(state.fareByCandidateId[candidate.id]!.normalFareYen,isNull);
        expect(state.fareByCandidateId[candidate.id]!.payNowYen,0);
        final scroll=find.descendant(of:find.byType(CustomScrollView).first,
            matching:find.byType(Scrollable)).first;
        tester.state<ScrollableState>(scroll).position.jumpTo(
            tester.state<ScrollableState>(scroll).position.maxScrollExtent);
        await tester.pump();
        await _reveal(tester,find.byType(RouteCard).first);
        expect(find.text('到着目安 ${c[2]}'),findsOneWidget);
        await tester.tap(find.byType(RouteCard).first);
        await tester.pumpAndSettle();
        expect(find.byType(RouteDetailPage),findsOneWidget);
        expect(find.textContaining('本人の有効なふれあい乗車証'),findsWidgets);
        final detail=tester.widget<RouteDetailPage>(find.byType(RouteDetailPage));
        expect(detail.candidate.id,candidate.id);
        expect(detail.candidate.steps.where((s)=>s.isRide).every((s)=>
            s.tripId!.startsWith('sendai_') && s.routeId!.startsWith('sendai_')),isTrue);
        navigator.pop();await tester.pumpAndSettle();
      }
      _stage='existing MapPickerPage selection and confirm contract';
      notifier.setFrom('');notifier.setTo('');
      notifier.setStartTime(DateTime(2026,11,19,9));notifier.setBusOnly(true);
      await tester.pump();
      await _reveal(tester,find.byKey(const Key('route-map-origin')));
      await tester.tap(find.byKey(const Key('route-map-origin')));
      await tester.pumpAndSettle();
      expect(tester.widget<MapPickerPage>(find.byType(MapPickerPage)).initialCenter.latitude,38.2601);
      await tester.longPress(find.byKey(const Key('ci-maps-render-surface')));
      await tester.pump();
      final l10n=AppLocalizations.of(tester.element(find.byType(MapPickerPage)));
      await tester.tap(find.text(l10n.mapConfirm));await tester.pumpAndSettle();
      expect(container.read(routeSearchProvider).from,'38.22439,140.87613');
      await _place(tester,'destination','長町駅西口');
      await _wait(tester,()=>container.read(routeSearchProvider).to.isNotEmpty);
      await _reveal(tester,find.byKey(const Key('route-search-submit')));
      await tester.tap(find.byKey(const Key('route-search-submit')));
      await _wait(tester,()=>!container.read(routeSearchProvider).isLoading);
      final surface=container.read(routeSearchProvider);
      expect(surface.errorMessage,isNull);expect(surface.candidates.first.arrivalTime,'09:24');
      expect(surface.candidates.first.steps.first.kind,'walk');
      expect(surface.candidates.first.steps.first.planningDetails!['walking_time_measured'],isFalse);
      _stage='map-origin result card and route detail';
      final resultScroll=find.descendant(of:find.byType(CustomScrollView).first,
          matching:find.byType(Scrollable)).first;
      tester.state<ScrollableState>(resultScroll).position.jumpTo(
          tester.state<ScrollableState>(resultScroll).position.maxScrollExtent);
      await tester.pump();
      await _reveal(tester,find.byType(RouteCard).first);
      expect(find.text('到着目安 09:24'),findsOneWidget);
      await tester.tap(find.byType(RouteCard).first);
      await tester.pumpAndSettle();
      final surfaceDetail=tester.widget<RouteDetailPage>(find.byType(RouteDetailPage));
      expect(surfaceDetail.candidate.id,surface.candidates.first.id);
      expect(surfaceDetail.candidate.steps.first.planningDetails!['walking_time_measured'],isFalse);
      expect(surfaceDetail.fare!.normalFareYen,isNull);
      expect(surfaceDetail.fare!.payNowYen,0);
      expect(find.textContaining('本人の有効なふれあい乗車証'),findsWidgets);
      _stage='preserve Japan civil query time in the existing detail date picker';
      await tester.tap(find.byKey(const Key('route-detail-research')));
      await tester.pumpAndSettle();
      expect(tester.widget<CupertinoDatePicker>(find.byType(CupertinoDatePicker)).initialDateTime,
          DateTime(2026,11,19,9));
      navigator.pop();await tester.pumpAndSettle();
      print('NORMAL_SENDAI_REAL_ROUTE_UI_OK; Places upstream fixture; Maps picker contract fixture, live SDK unverified');
    } catch(error,stack) {
      print('NORMAL_UI_STAGE=$_stage\n$error\n$stack');
      Error.throwWithStackTrace(error,stack);
    }
  },timeout:const Timeout(Duration(minutes:8)));
}
