import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/models/fare_models.dart';
import 'package:toeigo/services/fare_policy_preferences.dart';

void main() {
  group('FareQuote', () {
    test('parses explicit free-pass fields', () {
      final quote = FareQuote.fromJson({
        'normalFareYen': 210,
        'payNowYen': 0,
        'effectiveFareYen': 0,
        'policyId': 'nagoya_welfare_special_pass',
        'settlementType': 'free_pass',
        'status': 'available',
        'unavailableReason': null,
      });

      expect(quote.normalFareYen, 210);
      expect(quote.payNowYen, 0);
      expect(quote.effectiveFareYen, 0);
      expect(quote.settlementLabel, '無料乗車証');
      expect(quote.isAvailable, isTrue);
    });

    test('unavailable fare must include a reason', () {
      expect(
        () => FareQuote.fromJson({
          'normalFareYen': null,
          'payNowYen': null,
          'effectiveFareYen': null,
          'policyId': 'normal',
          'settlementType': 'normal',
          'status': 'unavailable',
          'unavailableReason': null,
        }),
        throwsFormatException,
      );
    });

    test('unknown settlement type fails fast', () {
      expect(
        () => FareQuote.fromJson({
          'normalFareYen': 210,
          'payNowYen': 210,
          'effectiveFareYen': 210,
          'policyId': 'normal',
          'settlementType': 'mystery',
          'status': 'available',
        }),
        throwsFormatException,
      );
    });
  });

  group('FarePolicyPreferences', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('first use defaults to normal only when nothing is stored', () async {
      final id = await FarePolicyPreferences.load(nagoyaCityProfile);
      expect(id, 'normal');
    });

    test('explicit selected policy is stored per city', () async {
      await FarePolicyPreferences.save(
        nagoyaCityProfile,
        'nagoya_welfare_special_pass',
      );
      await FarePolicyPreferences.save(
        tokyoCityProfile,
        'tokyo_toei_transport_pass',
      );

      expect(
        await FarePolicyPreferences.load(nagoyaCityProfile),
        'nagoya_welfare_special_pass',
      );
      expect(
        await FarePolicyPreferences.load(tokyoCityProfile),
        'tokyo_toei_transport_pass',
      );
    });

    test('stored policy from another city is not silently replaced', () async {
      SharedPreferences.setMockInitialValues({
        'farePolicyId:nagoya': 'tokyo_toei_transport_pass',
      });

      await expectLater(
        FarePolicyPreferences.load(nagoyaCityProfile),
        throwsStateError,
      );
    });

    test('saving an unsupported policy fails before persistence', () async {
      await expectLater(
        FarePolicyPreferences.save(
          nagoyaCityProfile,
          'tokyo_toei_transport_pass',
        ),
        throwsStateError,
      );
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('farePolicyId:nagoya'), isNull);
    });
  });
}
