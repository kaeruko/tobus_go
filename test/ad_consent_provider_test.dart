import 'package:flutter_test/flutter_test.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:toeigo/providers/ad_consent_provider.dart';

class FakeConsentGateway implements ConsentGateway {
  final calls = <String>[];
  bool allowed = true;
  bool required = true;
  String? failAt;

  void record(String call) {
    calls.add(call);
    if (failAt == call) throw StateError(call);
  }

  @override
  Future<void> update() async => record('update');
  @override
  Future<void> showRequiredForm() async => record('form');
  @override
  Future<bool> privacyOptionsRequired() async {
    record('privacy');
    return required;
  }

  @override
  Future<bool> canRequestAds() async {
    record('allowed');
    return allowed;
  }

  @override
  Future<void> showPrivacyOptions() async => record('options');
}

void main() {
  test(
    'UMP debug geography requires explicit debug mode and a test device',
    () {
      for (final (region, expected) in [
        ('eea', DebugGeography.debugGeographyEea),
        ('regulated-us', DebugGeography.debugGeographyRegulatedUsState),
        ('other', DebugGeography.debugGeographyOther),
      ]) {
        final settings = umpDebugSettings(
          enabled: true,
          geography: region,
          testDeviceId: 'HASH',
        );
        expect(settings?.debugGeography, expected);
        expect(settings?.testIdentifiers, ['HASH']);
      }
      expect(
        umpDebugSettings(
          enabled: false,
          geography: 'eea',
          testDeviceId: 'HASH',
        ),
        isNull,
      );
      expect(
        umpDebugSettings(enabled: true, geography: '', testDeviceId: ''),
        isNull,
      );
      for (final (region, id) in [
        ('eea', ''),
        ('', 'HASH'),
        ('unknown', 'HASH'),
      ]) {
        expect(
          () => umpDebugSettings(
            enabled: true,
            geography: region,
            testDeviceId: id,
          ),
          throwsStateError,
        );
      }
    },
  );

  test(
    'requests update once and only permits ads after required form',
    () async {
      final gateway = FakeConsentGateway();
      final controller = AdConsentController(gateway);
      addTearDown(controller.dispose);
      expect(controller.state.canRequestAds, isFalse);
      await controller.start();
      await controller.start();
      expect(gateway.calls, [
        'update',
        'privacy',
        'form',
        'privacy',
        'allowed',
      ]);
      expect(controller.state.canRequestAds, isTrue);
      expect(controller.state.privacyOptionsRequired, isTrue);
      gateway.allowed = false;
      await controller.showPrivacyOptions();
      expect(controller.state.canRequestAds, isFalse);
      expect(gateway.calls.sublist(5), ['options', 'privacy', 'allowed']);
    },
  );

  for (final stage in ['update', 'privacy', 'form', 'allowed']) {
    test('consent failure at $stage blocks ads', () async {
      final gateway = FakeConsentGateway()..failAt = stage;
      final controller = AdConsentController(gateway);
      addTearDown(controller.dispose);
      await controller.start();
      expect(controller.state.canRequestAds, isFalse);
      expect(controller.state.busy, isFalse);
      expect(gateway.calls.last, stage);
    });
  }

  test(
    'UMP denial at startup blocks ads but keeps required privacy options',
    () async {
      final gateway = FakeConsentGateway()..allowed = false;
      final controller = AdConsentController(gateway);
      addTearDown(controller.dispose);
      await controller.start();
      expect(controller.state.canRequestAds, isFalse);
      expect(controller.state.privacyOptionsRequired, isTrue);
    },
  );

  test('privacy options failure stops previously allowed ads', () async {
    final gateway = FakeConsentGateway();
    final controller = AdConsentController(gateway);
    addTearDown(controller.dispose);
    await controller.start();
    gateway.failAt = 'options';
    await controller.showPrivacyOptions();
    expect(controller.state.canRequestAds, isFalse);
    expect(controller.state.privacyOptionsRequired, isTrue);
    expect(gateway.calls.last, 'options');
  });
}
