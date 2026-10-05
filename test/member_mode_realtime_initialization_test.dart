import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('member mode initializes realtime after the first frame', () {
    final source = File('lib/pages/member_mode_page.dart').readAsStringSync();

    final classStart = source.indexOf('class _MemberModePageState');
    expect(classStart, greaterThanOrEqualTo(0));

    final initStart = source.indexOf('  void initState() {', classStart);
    expect(initStart, greaterThanOrEqualTo(0));

    final buildStart = source.indexOf('  Widget build(BuildContext context) {', initStart);
    expect(buildStart, greaterThan(initStart));

    final initStateSource = source.substring(initStart, buildStart);
    final postFrameIndex = initStateSource.indexOf(
      'WidgetsBinding.instance.addPostFrameCallback',
    );
    final resetIndex = initStateSource.indexOf(
      'ref.read(memberNavProgressProvider.notifier).reset();',
    );
    final initializeIndex = initStateSource.indexOf(
      'ref.read(memberModeControllerProvider.notifier).initialize();',
    );

    expect(postFrameIndex, greaterThanOrEqualTo(0));
    expect(resetIndex, greaterThan(postFrameIndex));
    expect(initializeIndex, greaterThan(resetIndex));
    expect(
      initStateSource.indexOf(
        'ref.read(memberModeControllerProvider.notifier).initialize();',
        initializeIndex + 1,
      ),
      -1,
    );
  });
}
