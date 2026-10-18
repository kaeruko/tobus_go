import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/services/route_search_service.dart';
import 'package:toeigo/widgets/sendai_pass_selector.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('senior card sends the same reviewed routing consent without free fare', () {
    final request = RouteSearchRequest(
      origin: const LatLng(38.26, 140.88),
      destination: const LatLng(38.30, 140.89),
      originName: '仙台',
      destinationName: '長町',
      startTime: DateTime(2026, 11, 19, 9),
      preference: 'fewTransfers',
      farePolicyId: 'sendai_keiro_pass',
      acceptExperimentalTransferModel: true,
    );
    final payload = request.toApiBody();
    expect(payload['fare_policy_id'], 'sendai_keiro_pass');
    expect(payload['accept_experimental_transfer_model'], isTrue);
    expect(payload['pref'], 'fewTransfers');
  });

  testWidgets('Sendai pass switch requires a tap and persists both choices', (tester) async {
    if (!sendaiReviewedCoordinatesEnabled) return;
    SharedPreferences.setMockInitialValues({});
    var changes = 0;
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(CupertinoApp(
      home: CupertinoPageScaffold(
        child: Center(child: SendaiPassSelector(
          onSelectionChanged: () => changes++,
        )),
      ),
    ));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('farePolicyId:sendai:reviewed-coordinate-development'), isNull);
    expect(find.text('ふれあい'), findsOneWidget);
    expect(find.text('敬老'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('敬老'));
    await tester.pumpAndSettle();
    expect(prefs.getString('farePolicyId:sendai:reviewed-coordinate-development'),
        'sendai_keiro_pass');
    expect(changes, 1);
    await tester.tap(find.text('ふれあい'));
    await tester.pumpAndSettle();
    expect(prefs.getString('farePolicyId:sendai:reviewed-coordinate-development'),
        'sendai_fureai_pass');
    expect(changes, 2);
    expect(tester.takeException(), isNull);
  });
}
