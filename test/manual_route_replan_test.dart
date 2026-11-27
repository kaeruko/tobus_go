import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/providers/group_schedule_impact_provider.dart';
import 'package:toeigo/providers/route_replanner_provider.dart';
import 'package:toeigo/providers/trip_provider.dart';
import 'package:toeigo/widgets/group_leader_route_replan_panel.dart';
import 'package:toeigo/widgets/route_replan_preview_button.dart';

Trip activeTrip(TripType type) => Trip(
  tripType: type,
  id: 'active-trip',
  joinCode: '',
  leaderId: 'user',
  title: 'Trip',
  travelPhase: TravelPhase.active,
  date: DateTime(2026, 11, 27),
  plannedDepartureAt: null,
  actualDepartureAt: null,
  legs: const [],
  schedule: const [],
  participants: const [],
  memberIds: const ['user'],
);

void main() {
  for (final type in TripType.values) {
    testWidgets('${type.name} manual replan stays safe without a warning card', (
      tester,
    ) async {
      final trip = activeTrip(type);
      const reason = 'Detailed realtime diagnostic must not be displayed';
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            tripStreamProvider.overrideWith((ref) => Stream.value(trip)),
            groupScheduleImpactProvider.overrideWith((ref) => null),
            currentRouteReplanRequestProvider.overrideWith((ref) => null),
            routeReplanBlockedReasonProvider.overrideWith((ref) => reason),
          ],
          child: MaterialApp(
            locale: const Locale('ja'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: type == TripType.solo
                  ? RouteReplanPreviewButton(trip: trip)
                  : const GroupLeaderRouteReplanContent(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('次の乗換えに間に合わない可能性があります'), findsNothing);
      expect(find.text(reason), findsNothing);
      expect(find.text('経路を見直す'), findsOneWidget);
      final button = tester.widget<OutlinedButton>(find.byType(OutlinedButton));
      expect(button.onPressed, isNull);
      expect(find.byType(RouteReplanPreviewButton), findsOneWidget);
    });
  }
}
