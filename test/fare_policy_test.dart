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
        'policyId': 'tokyo_toei_transport_pass',
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

    test('Tokyo first use defaults to normal only when nothing is stored', () async {
      expect(await FarePolicyPreferences.load(tokyoCityProfile), 'normal');
    });

    test('explicit Tokyo policy selection is persisted', () async {
      await FarePolicyPreferences.save(
        tokyoCityProfile, 'tokyo_toei_transport_pass',
      );
      expect(
        await FarePolicyPreferences.load(tokyoCityProfile),
        'tokyo_toei_transport_pass',
      );
    });

    test('stored unsupported policy is not silently replaced', () async {
      SharedPreferences.setMockInitialValues({
        'farePolicyId:tokyo': 'unsupported_fixture_pass',
      });
      await expectLater(
        FarePolicyPreferences.load(tokyoCityProfile), throwsStateError,
      );
    });

    test('unsupported policy fails before persistence', () async {
      await expectLater(
        FarePolicyPreferences.save(tokyoCityProfile, 'unsupported_fixture_pass'),
        throwsStateError,
      );
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('farePolicyId:tokyo'), isNull);
    });
  });
}
