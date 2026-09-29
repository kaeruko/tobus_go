import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/l10n/navigation_localizations.dart';
import 'package:toeigo/logic/trip_navigator.dart';

void main() {
  late AppLocalizations en;
  late AppLocalizations zh;

  setUpAll(() async {
    en = await AppLocalizations.delegate.load(const Locale('en'));
    zh = await AppLocalizations.delegate.load(const Locale('zh'));
  });

  test('Chinese navigation retains official English and Japanese places', () {
    const token = NavigationTextToken(NavigationTextKey.rideArrivalSummary, {
      'arrivalTime': '10:20',
      'rideTitle': '浅草線',
      'rideTitleEn': 'Asakusa Line',
      'destination': '蔵前',
      'destinationEn': 'Kuramae',
    });

    expect(
      localizedNavigationText(
        zh,
        const Locale('zh'),
        token,
        fallback: 'fallback',
      ),
      zh.navRideArrivalSummary('10:20', 'Asakusa Line', 'Kuramae (蔵前)'),
    );
  });

  test('Chinese navigation requires the same official names as English', () {
    for (final english in <String?>[null, '', '   ']) {
      final token = NavigationTextToken(NavigationTextKey.nowAtSub, {
        'placeName': '蔵前',
        if (english != null) 'placeNameEn': english,
      });

      expect(
        () => localizedNavigationText(
          zh,
          const Locale('zh'),
          token,
          fallback: 'fallback',
        ),
        throwsStateError,
      );
    }
  });

  test('Chinese generic walk places retain optional bilingual behavior', () {
    for (final english in <String?>[null, 'Park plaza']) {
      final token = NavigationTextToken(NavigationTextKey.walkHeadingMain, {
        'destination': '公園内広場',
        if (english != null) 'destinationEn': english,
      });

      expect(
        localizedNavigationText(
          zh,
          const Locale('zh'),
          token,
          fallback: 'fallback',
        ),
        zh.navWalkHeadingMain(english == null ? '公園内広場' : 'Park plaza (公園内広場)'),
      );
    }
  });

  test('transit navigation place requires official English diagnostic', () {
    final token = NavigationTextToken(NavigationTextKey.nowAtSub, const {
      'placeName': '蔵前',
    });

    expect(
      () => localizedNavigationText(
        en,
        const Locale('en'),
        token,
        fallback: 'fallback',
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message.toString(),
          'diagnostic',
          allOf(contains('nowAtSub'), contains('placeNameEn')),
        ),
      ),
    );
  });

  test('generic walk navigation may omit English destination', () {
    final token = NavigationTextToken(NavigationTextKey.walkHeadingMain, const {
      'destination': '公園内広場',
    });

    expect(
      localizedNavigationText(
        en,
        const Locale('en'),
        token,
        fallback: 'fallback',
      ),
      'Head to 公園内広場',
    );
  });

  test('generic walk navigation rejects blank optional English', () {
    final token = NavigationTextToken(NavigationTextKey.walkHeadingMain, const {
      'destination': '公園内広場',
      'destinationEn': '   ',
    });

    expect(
      () => localizedNavigationText(
        en,
        const Locale('en'),
        token,
        fallback: 'fallback',
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message.toString(),
          'diagnostic',
          allOf(contains('walkHeadingMain'), contains('destinationEn')),
        ),
      ),
    );
  });
}
