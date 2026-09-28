import 'dart:async';

import 'package:flutter/material.dart';

import '../core/app_clock.dart';
import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../services/timetable_service.dart';

class TimetableView extends StatefulWidget {
  final String routeId;
  final String stopId;
  final String? targetPoleId;
  final int limit;
  final bool showEmptyState;
  final bool showFullDay;

  const TimetableView({
    super.key,
    required this.routeId,
    required this.stopId,
    this.targetPoleId,
    this.limit = 3,
    this.showEmptyState = false,
    this.showFullDay = false,
  });

  @override
  State<TimetableView> createState() => _TimetableViewState();
}

class _TimetableViewState extends State<TimetableView> {
  final TimetableService _service = TimetableService();
  final GlobalKey _currentHourKey = GlobalKey();

  List<Map<String, dynamic>> _busGroups = [];
  String _dayType = '';
  DateTime _now = appClock.now();
  Timer? _timer;
  bool _isLoading = true;
  bool _didAutoScroll = false;

  @override
  void initState() {
    super.initState();
    _initData();
    _timer = Timer.periodic(const Duration(minutes: 1), (_) {
      _now = appClock.now();
      _updateBusInfo();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _initData() async {
    _dayType = _service.getTodayType();
    await _updateBusInfo();
    if (mounted) {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _updateBusInfo() async {
    final groups = await _service.getNextBusesFromApi(
      widget.routeId,
      widget.stopId,
      targetPoleId: widget.targetPoleId,
      limit: widget.limit,
      includeAllDay: widget.showFullDay,
    );
    if (!mounted) return;

    setState(() => _busGroups = groups);

    if (widget.showFullDay && !_didAutoScroll) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final targetContext = _currentHourKey.currentContext;
        if (!mounted || targetContext == null) return;
        _didAutoScroll = true;
        Scrollable.ensureVisible(
          targetContext,
          alignment: 0.25,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }

    final dayTypeLabel = switch (_dayType) {
      'Weekday' => l10n.dayWeekday,
      'Saturday' => l10n.daySaturday,
      'Holiday' => l10n.dayHoliday,
      _ => throw StateError('Unsupported timetable day type: $_dayType'),
    };

    if (_busGroups.isEmpty) {
      if (!widget.showEmptyState) return const SizedBox.shrink();
      return Text(
        l10n.timetableNoDepartures,
        style: const TextStyle(fontSize: 14, color: Colors.grey),
      );
    }

    final locale = Localizations.localeOf(context);
    if (widget.showFullDay) {
      return _buildFullDay(l10n, locale, dayTypeLabel);
    }
    return _buildUpcoming(l10n, locale, dayTypeLabel);
  }

  Widget _buildUpcoming(
    AppLocalizations l10n,
    Locale locale,
    String dayTypeLabel,
  ) {
    final upcomingGroups = _busGroups
        .where((group) => (group['times'] as List<String>).isNotEmpty)
        .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionHeader(l10n.nextBus(dayTypeLabel)),
        const SizedBox(height: 6),
        if (upcomingGroups.isEmpty)
          Text(
            l10n.timetableNoDepartures,
            style: const TextStyle(fontSize: 14, color: Colors.grey),
          )
        else
          ...upcomingGroups.map(
            (group) => _upcomingDestinationRow(locale, group),
          ),
      ],
    );
  }

  Widget _buildFullDay(
    AppLocalizations l10n,
    Locale locale,
    String dayTypeLabel,
  ) {
    final upcomingGroups = _busGroups
        .where((group) => (group['times'] as List<String>).isNotEmpty)
        .toList();
    final fullGroups = _busGroups
        .where((group) => (group['allTimes'] as List<String>).isNotEmpty)
        .toList();

    final targetHour = _relevantHour(fullGroups);
    var currentHourKeyAssigned = false;
    final fullDayChildren = <Widget>[];

    for (final group in fullGroups) {
      final destination = _localizedDestination(locale, group);
      final grouped = _groupTimesByHour(group['allTimes'] as List<String>);
      if (grouped.isEmpty) continue;

      fullDayChildren.add(
        Padding(
          padding: const EdgeInsets.fromLTRB(0, 8, 0, 6),
          child: Text(
            destination,
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
          ),
        ),
      );

      final hours = grouped.keys.toList()..sort();
      for (final hour in hours) {
        final useCurrentKey =
            !currentHourKeyAssigned && targetHour != null && hour == targetHour;
        if (useCurrentKey) currentHourKeyAssigned = true;

        fullDayChildren.add(
          Container(
            key: useCurrentKey ? _currentHourKey : null,
            padding: const EdgeInsets.symmetric(vertical: 7),
            decoration: const BoxDecoration(
              border: Border(
                bottom: BorderSide(color: Color(0xFFE5E5EA), width: 0.5),
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 54,
                  child: Text(
                    l10n.timetableHour(hour),
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: hour == targetHour
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                  ),
                ),
                Expanded(
                  child: Wrap(
                    spacing: 14,
                    runSpacing: 6,
                    children: grouped[hour]!
                        .map(
                          (minute) => Text(
                            minute,
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        )
                        .toList(),
                  ),
                ),
              ],
            ),
          ),
        );
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionHeader(l10n.nextThreeBuses(dayTypeLabel)),
        const SizedBox(height: 6),
        if (upcomingGroups.isEmpty)
          Text(
            l10n.timetableNoDepartures,
            style: const TextStyle(fontSize: 14, color: Colors.grey),
          )
        else
          ...upcomingGroups.map(
            (group) => _upcomingDestinationRow(locale, group),
          ),
        const SizedBox(height: 12),
        const Divider(height: 1),
        const SizedBox(height: 12),
        _sectionHeader(l10n.fullTimetable),
        const SizedBox(height: 4),
        Expanded(
          child: fullDayChildren.isEmpty
              ? Text(
                  l10n.timetableNoDepartures,
                  style: const TextStyle(fontSize: 14, color: Colors.grey),
                )
              : ListView(
                  padding: EdgeInsets.zero,
                  children: fullDayChildren,
                ),
        ),
      ],
    );
  }

  Widget _sectionHeader(String label) {
    return Row(
      children: [
        const Icon(Icons.access_time, size: 14, color: Colors.grey),
        const SizedBox(width: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 12, color: Colors.grey),
        ),
      ],
    );
  }

  Widget _upcomingDestinationRow(
    Locale locale,
    Map<String, dynamic> group,
  ) {
    final destination = _localizedDestination(locale, group);
    final times = group['times'] as List<String>;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            constraints: const BoxConstraints(maxWidth: 130),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: Colors.blue[50],
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: Colors.blue[100]!),
            ),
            child: Text(
              destination,
              style: TextStyle(
                fontSize: 11,
                color: Colors.blue[900],
                fontWeight: FontWeight.bold,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (var index = 0; index < times.length; index++)
                    Padding(
                      padding: const EdgeInsets.only(right: 10),
                      child: Text(
                        times[index],
                        style: TextStyle(
                          fontSize: index == 0 ? 16 : 14,
                          fontWeight: FontWeight.bold,
                          color: index == 0 ? Colors.black87 : Colors.grey[600],
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _localizedDestination(
    Locale locale,
    Map<String, dynamic> group,
  ) {
    final japanese = group['destinationName'] as String;
    final english = group['destinationNameEn'] as String?;
    final destinationPoleId = group['destinationPoleId'] as String?;
    return localizedTransitName(
      locale,
      japanese: japanese,
      english: english,
      field: 'destination_name_en',
      identity: 'destinationPoleId=${destinationPoleId ?? '<unknown>'}',
    );
  }

  Map<int, List<String>> _groupTimesByHour(List<String> times) {
    final grouped = <int, List<String>>{};
    for (final value in times) {
      final match = RegExp(r'^(\d{1,2}):([0-5]\d)$').firstMatch(value);
      if (match == null) {
        throw StateError('Invalid timetable time: $value');
      }
      final hour = int.parse(match.group(1)!);
      final minute = match.group(2)!;
      grouped.putIfAbsent(hour, () => <String>[]).add(minute);
    }
    return grouped;
  }

  int? _relevantHour(List<Map<String, dynamic>> groups) {
    final hours = <int>{};
    for (final group in groups) {
      hours.addAll(
        _groupTimesByHour(group['allTimes'] as List<String>).keys,
      );
    }
    if (hours.isEmpty) return null;

    final ordered = hours.toList()..sort();
    for (final hour in ordered) {
      if (hour >= _now.hour) return hour;
    }
    return ordered.last;
  }
}
