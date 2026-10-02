import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('public settings only expose name and join-trip actions', () {
    final source = File('lib/pages/settings_page.dart').readAsStringSync();

    expect(source, contains('title: Text(l10n.settingsUserName)'));
    expect(source, contains('title: Text(l10n.settingsJoinTrip)'));
    expect(source, isNot(contains('settingsUserId')));
    expect(source, isNot(contains('settingsEnableStaff')));
    expect(source, isNot(contains('settingsOpenAsMember')));
  });

  test('developer controls are gated by debug mode', () {
    final source = File('lib/pages/settings_page.dart').readAsStringSync();

    expect(source, contains('if (kDebugMode) ...['));
    expect(source, contains('title: Text(l10n.settingsAdminMenu)'));
    expect(source, contains('l10n.settingsManualLocation'));
    expect(source, contains('title: Text(l10n.settingsTimeOffset)'));
  });
}
