import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/widgets/timetable_view.dart';

void main() {
  testWidgets(
    'next-bus timetable fetches once and updates locally on minute ticks',
    (tester) async {
      final originalClient = ApiClient.httpClient;
      configureApiBase(Uri.parse('https://api.example.test'));

      var requestCount = 0;
      ApiClient.httpClient = MockClient((request) async {
        requestCount += 1;
        expect(request.url.path, '/bus/next');
        expect(request.url.queryParameters['pole_id'], 'stop-a');
        expect(request.url.queryParameters['route_id'], 'route-a');
        expect(request.url.queryParameters['target_pole_id'], 'stop-b');
        expect(request.url.queryParameters['include_all'], 'true');

        return http.Response(
          '{"destinations":[{"destination_pole_id":"stop-b",'
          '"destination_name":"新橋",'
          '"destination_name_en":"Shimbashi",'
          '"times":["23:58","24:10","24:30"],'
          '"all_times":["00:10","06:00","12:00","18:00","23:58","24:10","24:30"]}]}',
          200,
          headers: const {'content-type': 'application/json; charset=utf-8'},
        );
      });
      addTearDown(() => ApiClient.httpClient = originalClient);

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const Scaffold(
            body: TimetableView(
              routeId: 'route-a',
              stopId: 'stop-a',
              targetPoleId: 'stop-b',
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(requestCount, 1);
      expect(tester.takeException(), isNull);

      await tester.pump(const Duration(minutes: 5));
      await tester.pump();

      expect(requestCount, 1);
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    },
  );
}
