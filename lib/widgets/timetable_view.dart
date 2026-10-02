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
    try {
      await _updateBusInfo();
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _selectDayType(String dayType) async {
    const supportedDayTypes = {'Weekday', 'Saturday', 'Holiday'};
    if (!supportedDayTypes.contains(dayType)) {
      throw ArgumentError.value(
        dayType,
        'dayType',
        'must be Weekday, Saturday, or Holiday',
      );
    }
    if (_dayType == dayType || _isLoading) return;

    setState(() {
      _dayType = dayType;
      _isLoading = true;
      _didAutoScroll = false;
    });

    try {
      await _updateBusInfo();
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _updateBusInfo() async {
    final groups = await _service.getNextBusesFromApi(
      widget.routeId,
      widget.stopId,
      targetPoleId: widget.targetPoleId,
      dayType: widget.showFullDay ? _dayType : null,
      referenceTime: _now,
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

    final dayTypeLabel = _dayTypeLabel(l10n, _dayType);
    final locale = Localizations.localeOf(context);

    if (widget.showFullDay) {
      return _buildFullDay(l10n, locale);
    }

    if (_busGroups.isEmpty) {
      if (!widget.showEmptyState) return const SizedBox.shrink();
      return Text(
        l10n.timetableNoDepartures,
        style: const TextStyle(fontSize: 14, color: Colors.grey),
      );
    }

    return _buildUpcoming(l10n, locale, dayTypeLabel);
  }

  String _dayTypeLabel(AppLocalizations l10n, String dayType) {
    return switch (dayType) {
      'Weekday' => l10n.dayWeekday,
      'Saturday' => l10n.daySaturday,
      'Holiday' => l10n.dayHoliday,
      _ => throw StateError('Unsupported timetable day type: $dayType'),
    };
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
  ) {
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
          padding: const EdgeInsets.fromLTRB(2, 14, 2, 7),
          child: Text(
            destination,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      );

      final hours = grouped.keys.toList()..sort();
      for (final hour in hours) {
        final isCurrentHour = targetHour != null && hour == targetHour;
        final useCurrentKey = !currentHourKeyAssigned && isCurrentHour;
        if (useCurrentKey) currentHourKeyAssigned = true;

        fullDayChildren.add(
          _timetableHourRow(
            hour: hour,
            minutes: grouped[hour]!,
            isCurrentHour: isCurrentHour,
            rowKey: useCurrentKey ? _currentHourKey : null,
          ),
        );
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _dayTypeTabs(l10n),
        const SizedBox(height: 4),
        Expanded(
          child: fullDayChildren.isEmpty
              ? Center(
                  child: Text(
                    l10n.timetableNoDepartures,
                    style: const TextStyle(
                      fontSize: 14,
                      color: Colors.grey,
                    ),
                  ),
                )
              : ListView(
                  padding: EdgeInsets.zero,
                  children: fullDayChildren,
                ),
        ),
      ],
    );
  }

  Widget _dayTypeTabs(AppLocalizations l10n) {
    final tabs = <(String, String)>[
      ('Weekday', l10n.dayWeekday),
      ('Saturday', l10n.daySaturday),
      ('Holiday', l10n.dayHoliday),
    ];

    return Container(
      height: 38,
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F0F4),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          for (final tab in tabs)
            Expanded(
              child: GestureDetector(
                key: ValueKey('timetable-day-${tab.$1}'),
                behavior: HitTestBehavior.opaque,
                onTap: () => _selectDayType(tab.$1),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  curve: Curves.easeOut,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: _dayType == tab.$1
                        ? const Color(0xFF0A84FF)
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    tab.$2,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: _dayType == tab.$1
                          ? Colors.white
                          : const Color(0xFF2C2C2E),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _timetableHourRow({
    required int hour,
    required List<String> minutes,
    required bool isCurrentHour,
    Key? rowKey,
  }) {
    return Container(
      key: rowKey ?? ValueKey('timetable-hour-$hour'),
      decoration: BoxDecoration(
        color: isCurrentHour ? const Color(0xFFF1F7FF) : Colors.transparent,
        border: const Border(
          bottom: BorderSide(color: Color(0xFFE5E5EA), width: 0.5),
        ),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              width: 50,
              constraints: const BoxConstraints(minHeight: 43),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: isCurrentHour
                    ? const Color(0xFF0A84FF)
                    : const Color(0xFFF7F7F9),
                border: const Border(
                  right: BorderSide(color: Color(0xFFE5E5EA), width: 0.5),
                ),
              ),
              child: Text(
                hour.toString().padLeft(2, '0'),
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: isCurrentHour
                      ? Colors.white
                      : const Color(0xFF1C1C1E),
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                child: Wrap(
                  spacing: 18,
                  runSpacing: 8,
                  children: [
                    for (final minute in minutes)
                      Text(
                        minute,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF1C1C1E),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
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
