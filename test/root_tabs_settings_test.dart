import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('root tabs wire settings into the bottom navigation', () {
    final source = File('lib/pages/root_tabs.dart').readAsStringSync();

    expect(
      source,
      contains("label: l10n.tabSettings"),
      reason: '設定タブのラベルがRootTabsに配線されていません',
    );
    expect(
      source,
      contains("page: const SettingsPage()"),
      reason: '設定タブがSettingsPageに配線されていません',
    );
  });
}
