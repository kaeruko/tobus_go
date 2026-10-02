import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/logic/group_schedule_sections.dart';
import 'package:toeigo/models/group_models.dart';

ScheduleEntry entry({
  required String id,
  required DateTime at,
  required int legIndex,
  required ScheduleEntrySource source,
}) {
  return ScheduleEntry(
    id: id,
    plannedAt: at,
    label: id,
    legIndex: legIndex,
    generatedBy: source,
  );
}

void main() {
  test('groups route legs around manual destination plans', () {
    final sections = GroupScheduleSections.fromEntries([
      entry(
        id: 'return-walk',
        at: DateTime(2026, 10, 2, 13, 10),
        legIndex: 1,
        source: ScheduleEntrySource.route,
      ),
      entry(
        id: 'lunch',
        at: DateTime(2026, 10, 2, 12, 0),
        legIndex: 0,
        source: ScheduleEntrySource.manual,
      ),
      entry(
        id: 'outbound-arrival',
        at: DateTime(2026, 10, 2, 11, 22),
        legIndex: 0,
        source: ScheduleEntrySource.route,
      ),
      entry(
        id: 'outbound-start',
        at: DateTime(2026, 10, 2, 10, 37),
        legIndex: 0,
        source: ScheduleEntrySource.route,
      ),
      entry(
        id: 'return-meeting',
        at: DateTime(2026, 10, 2, 13, 0),
        legIndex: 1,
        source: ScheduleEntrySource.route,
      ),
    ]);

    expect(
      sections.outboundRoute.map((e) => e.id),
      ['outbound-start', 'outbound-arrival'],
    );
    expect(sections.onsiteEntries.map((e) => e.id), ['lunch']);
    expect(
      sections.inboundRoute.map((e) => e.id),
      ['return-meeting', 'return-walk'],
    );

    final window = sections.requireOnsiteWindow();
    expect(window.start, DateTime(2026, 10, 2, 11, 22));
    expect(window.end, DateTime(2026, 10, 2, 13, 0));
    expect(window.contains(DateTime(2026, 10, 2, 12, 0)), isTrue);
    expect(window.contains(DateTime(2026, 10, 2, 13, 0)), isFalse);
  });

  test('manual entries remain destination plans regardless of stored leg index', () {
    final sections = GroupScheduleSections.fromEntries([
      entry(
        id: 'outbound-arrival',
        at: DateTime(2026, 10, 2, 11, 0),
        legIndex: 0,
        source: ScheduleEntrySource.route,
      ),
      entry(
        id: 'legacy-manual',
        at: DateTime(2026, 10, 2, 12, 0),
        legIndex: 1,
        source: ScheduleEntrySource.manual,
      ),
      entry(
        id: 'return-meeting',
        at: DateTime(2026, 10, 2, 13, 0),
        legIndex: 1,
        source: ScheduleEntrySource.route,
      ),
    ]);

    expect(sections.onsiteEntries.single.id, 'legacy-manual');
  });

  test('fails when there is no gap between outbound and return', () {
    final sections = GroupScheduleSections.fromEntries([
      entry(
        id: 'outbound-arrival',
        at: DateTime(2026, 10, 2, 13, 0),
        legIndex: 0,
        source: ScheduleEntrySource.route,
      ),
      entry(
        id: 'return-meeting',
        at: DateTime(2026, 10, 2, 13, 0),
        legIndex: 1,
        source: ScheduleEntrySource.route,
      ),
    ]);

    expect(sections.requireOnsiteWindow, throwsStateError);
  });
}
