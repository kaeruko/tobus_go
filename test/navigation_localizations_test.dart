import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/l10n/navigation_localizations.dart';
import 'package:toeigo/logic/trip_navigator.dart';

void main() {
  late AppLocalizations en;

  setUpAll(() async {
    en = await AppLocalizations.delegate.load(const Locale('en'));
  });

  test('transit navigation place requires official English diagnostic', () {
    final token = NavigationTextToken(
      NavigationTextKey.nowAtSub,
      const {'placeName': '蔵前'},
    );

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
          allOf(
            contains('nowAtSub'),
            contains('placeNameEn'),
          ),
        ),
      ),
    );
  });

  test('generic walk navigation may omit English destination', () {
    final token = NavigationTextToken(
      NavigationTextKey.walkHeadingMain,
      const {'destination': '公園内広場'},
    );

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
    final token = NavigationTextToken(
      NavigationTextKey.walkHeadingMain,
      const {
        'destination': '公園内広場',
        'destinationEn': '   ',
      },
    );

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
          allOf(
            contains('walkHeadingMain'),
            contains('destinationEn'),
          ),
        ),
      ),
    );
  });
}
