import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/services.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../services/user_service.dart';
import '../services/trip_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_session_provider.dart';
import '../providers/location_provider.dart';
import '../widgets/place_field.dart';
import 'leader_mode_page.dart';
import '../core/app_clock.dart'; // 追加
import '../providers/minute_ticker_provider.dart';
import '../services/route_search_service.dart';
import '../models/leg_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../l10n/app_localizations.dart';
import 'trip_list_page.dart';
import 'trip_page.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  String _userName = '';
  String _manualLocationInput = '';

  @override
  void initState() {
    super.initState();
    _loadSettings();

    if (kDebugMode) {
      final override = ref.read(locationOverrideProvider);
      if (override != null) {
        _manualLocationInput = '${override.latitude},${override.longitude}';
      }
    }
  }

  Future<void> _loadSettings() async {
    await UserService().initialize();
    final name = await UserService().getUserName();
    if (!mounted) return;
    setState(() {
      _userName = name;
    });
  }

  Future<void> _updateUserName() async {
    final l10n = AppLocalizations.of(context);
    final controller = TextEditingController(text: _userName);
    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l10n.settingsChangeUserName),
        content: TextField(
          controller: controller,
          decoration: InputDecoration(labelText: l10n.settingsNewName),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l10n.cancel),
          ),
          TextButton(
            onPressed: () async {
              final newName = controller.text.trim();
              if (newName.isNotEmpty) {
                await UserService().updateUserName(newName);
                setState(() {
                  _userName = newName;
                });
              }
              if (context.mounted) Navigator.pop(context);
            },
            child: Text(l10n.settingsSave),
          ),
        ],
      ),
    );
  }

  Future<void> _showJoinTripDialog() async {
    final l10n = AppLocalizations.of(context);
    final controller = TextEditingController();
    String? validationError;
    var joining = false;

    try {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) {
          return StatefulBuilder(
            builder: (context, setDialogState) {
              Future<void> submit() async {
                if (joining) return;

                final code = controller.text.trim();
                if (!RegExp(r'^\\d{6}$').hasMatch(code)) {
                  setDialogState(() {
                    validationError = l10n.settingsJoinCodeInvalid;
                  });
                  return;
                }

                setDialogState(() {
                  joining = true;
                  validationError = null;
                });

                try {
                  final tripId = await TripService().joinTrip(code);
                  await ref
                      .read(appSessionProvider.notifier)
                      .enterMemberMode(tripId);

                  if (!dialogContext.mounted) return;
                  Navigator.pop(dialogContext);
                  if (!mounted) return;
                  Navigator.of(this.context).pop();
                } catch (error) {
                  if (!dialogContext.mounted) return;
                  setDialogState(() {
                    joining = false;
                    validationError = error.toString();
                  });
                }
              }

              return AlertDialog(
                title: Text(l10n.settingsJoinCodeTitle),
                content: TextField(
                  controller: controller,
                  autofocus: true,
                  enabled: !joining,
                  keyboardType: TextInputType.number,
                  textInputAction: TextInputAction.done,
                  maxLength: 6,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(6),
                  ],
                  decoration: InputDecoration(
                    labelText: l10n.settingsJoinCodeHint,
                    border: const OutlineInputBorder(),
                    errorText: validationError,
                    counterText: '',
                  ),
                  onSubmitted: (_) => submit(),
                ),
                actions: [
                  TextButton(
                    onPressed: joining
                        ? null
                        : () => Navigator.pop(dialogContext),
                    child: Text(l10n.cancel),
                  ),
                  FilledButton(
                    onPressed: joining ? null : submit,
                    child: joining
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                            ),
                          )
                        : Text(l10n.settingsJoin),
                  ),
                ],
              );
            },
          );
        },
      );
    } finally {
      controller.dispose();
    }
  }

  void _updateManualLocation(String value, String desc) {
    setState(() => _manualLocationInput = value);

    final parts = value.split(',');
    if (parts.length != 2) {
      return;
    }

    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    if (lat == null || lon == null) {
      return;
    }

    ref.read(locationOverrideProvider.notifier).setOverride(LatLng(lat, lon));
  }

  Future<void> _clearManualLocation() async {
    await ref.read(locationOverrideProvider.notifier).clearOverride();
  }

  // ★追加: 時間オフセットの設定ダイアログ
  Future<void> _updateTimeOffset() async {
    final l10n = AppLocalizations.of(context);
    final currentOffset = AppClock.instance.offset;
    // 初期値設定
    final hController = TextEditingController(
      text: currentOffset.inHours.toString(),
    );
    final mController = TextEditingController(
      text: (currentOffset.inMinutes.remainder(60)).toString(),
    );

    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l10n.settingsTimeOffset),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              l10n.settingsTimeOffsetDescription,
              style: const TextStyle(fontSize: 12),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: hController,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: l10n.settingsHours,
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: mController,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: l10n.settingsMinutes,
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              AppClock.instance.resetOffset();
              ref.invalidate(
                minuteTickerProvider,
              ); // Force immediate time update
              setState(() {}); // 画面更新
              Navigator.pop(context);
            },
            child: Text(
              l10n.settingsReset,
              style: const TextStyle(color: Colors.red),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l10n.cancel),
          ),
          FilledButton(
            onPressed: () {
              final h = int.tryParse(hController.text) ?? 0;
              final m = int.tryParse(mController.text) ?? 0;
              AppClock.instance.setOffset(Duration(hours: h, minutes: m));
              ref.invalidate(
                minuteTickerProvider,
              ); // Force immediate time update
              setState(() {}); // 画面更新
              Navigator.pop(context);
            },
            child: Text(l10n.settingsApply),
          ),
        ],
      ),
    );
  }

  Future<void> _openLatestTripAsLeader() async {
    try {
      debugPrint("[Settings] _openLatestTripAsLeader called");
      String? tripId;
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      debugPrint("[Settings] sessionTripId: $sessionTripId");

      if (sessionTripId != null) {
        tripId = sessionTripId;
        debugPrint("[Settings] Using sessionTripId: $tripId");
      } else {
        final activeTrip = await TripService().getActiveTrip();
        debugPrint("[Settings] activeTrip from Service: ${activeTrip?.id}");
        if (activeTrip != null) {
          tripId = activeTrip.id;
          debugPrint("[Settings] Using activeTripId: $tripId");
        }
      }

      if (tripId == null) {
        final uid = UserService().currentUserId;
        debugPrint("[Settings] Current User ID: $uid");
        if (uid != null) {
          debugPrint("[Settings] Querying Firestore for leader trips...");
          final snapshot = await FirebaseFirestore.instance
              .collection('trips')
              .where('memberIds', arrayContains: uid)
              .orderBy('date', descending: true)
              .limit(1)
              .get();

          debugPrint("[Settings] Snapshot docs count: ${snapshot.docs.length}");
          if (snapshot.docs.isNotEmpty) {
            final doc = snapshot.docs.first;
            final data = doc.data();
            debugPrint(
              "[Settings] Found Leader Trip: ${doc.id} | Status: ${data['travelPhase'] ?? data['status']} | Date: ${data['date']}",
            );
            tripId = doc.id;
          }
        } else {
          debugPrint("[Settings] UID is null, skipping Firestore query");
        }
      }

      if (tripId != null) {
        final trip = await TripService().getTrip(tripId);
        if (trip?.isSolo == true) {
          final soloTrip = trip!;
          if (mounted) {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => TripPage(tripId: soloTrip.id)),
            );
          }
          return;
        }
        debugPrint(
          "[Settings] Attempting to open LeaderModePage for tripId: $tripId",
        );
        await ref.read(appSessionProvider.notifier).updateTripId(tripId);
        if (mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId!)),
          );
        }
      } else {
        debugPrint("[Settings] No tripId found for Leader Mode.");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(AppLocalizations.of(context).settingsNoTrip),
            ),
          );
        }
      }
    } catch (e) {
      debugPrint("[Settings] Error in _openLatestTripAsLeader: $e");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context).errorWithMessage(e.toString()),
            ),
          ),
        );
      }
    }
  }

  // 時刻表示用のヘルパー
  String _formatTime(DateTime dt) {
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _createDebugTrip() async {
    final l10n = AppLocalizations.of(context);
    try {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.settingsCreatingDebugTrip)));

      final now = AppClock.instance.now();
      final outboundTime = now.add(const Duration(minutes: 15));
      final returnTime = now.add(const Duration(hours: 2));

      const routeSearch = ApiRouteSearchService();

      // 1. Search outbound (Higashi-Sumida -> Nakaibori)
      final outboundResult = await routeSearch.search(
        RouteSearchRequest(
          origin: const LatLng(35.718754, 139.834261),
          destination: const LatLng(35.713601, 139.827539),
          originName: '東墨田三丁目',
          destinationName: '中居堀',
          startTime: outboundTime,
          preference: 'time',
        ),
      );
      if (outboundResult.candidates.isEmpty) {
        throw Exception(l10n.settingsDebugOutboundNotFound);
      }
      final candidateOut = outboundResult.candidates.first;

      // 2. Search inbound (Nakaibori -> Higashi-Sumida)
      final inboundResult = await routeSearch.search(
        RouteSearchRequest(
          origin: const LatLng(35.713601, 139.827539),
          destination: const LatLng(35.718754, 139.834261),
          originName: '中居堀',
          destinationName: '東墨田三丁目',
          startTime: returnTime,
          preference: 'time',
        ),
      );
      if (inboundResult.candidates.isEmpty) {
        throw Exception(l10n.settingsDebugInboundNotFound);
      }
      final candidateIn = inboundResult.candidates.first;

      // 3. Create Legs and Schedule
      final legs = [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidateOut,
          confirmedAt: now,
        ),
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: candidateIn,
          confirmedAt: now,
        ),
      ];

      final schedule = createScheduleFromLegs(
        legs,
        userSelectedStartTime: outboundTime,
        userSelectedReturnTime: returnTime,
      );

      // 4. Create Trip
      final tripId = await TripService().createTrip(legs, schedule);

      // 5. Open as Leader
      if (mounted) {
        await ref.read(appSessionProvider.notifier).updateTripId(tripId);
        if (!mounted) return;
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId)),
        );
      }
    } catch (e) {
      debugPrint('Diff debug trip failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context).errorWithMessage(e.toString()),
            ),
          ),
        );
      }
    }
  }

  Future<void> _deleteAllTrips() async {
    final l10n = AppLocalizations.of(context);
    try {
      if (!mounted) return;
      final confirm = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(l10n.settingsDeleteAllTitle),
          content: Text(l10n.settingsDeleteAllConfirmation),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: Text(l10n.cancel),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              style: TextButton.styleFrom(foregroundColor: Colors.red),
              child: Text(l10n.delete),
            ),
          ],
        ),
      );

      if (confirm != true) return;

      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(l10n.settingsDeleting)));
      }

      final snapshot = await FirebaseFirestore.instance
          .collection('trips')
          .get();
      final batch = FirebaseFirestore.instance.batch();
      for (final doc in snapshot.docs) {
        batch.delete(doc.reference);
      }
      await batch.commit();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).settingsAllTripsDeleted),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context).errorWithMessage(e.toString()),
            ),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (kDebugMode) {
      ref.listen<LatLng?>(locationOverrideProvider, (prev, next) {
        setState(() {
          _manualLocationInput = next != null
              ? '${next.latitude},${next.longitude}'
              : '';
        });
      });
    }

    final manualOverride = kDebugMode
        ? ref.watch(locationOverrideProvider)
        : null;
    final currentOffset = AppClock.instance.offset;
    final simulatedTime = AppClock.instance.now();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.tabSettings)),
      body: ListView(
        children: [
          // --- ユーザー情報 ---
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 24, 16, 8),
            child: Text(
              l10n.settingsUserInfo,
              style: const TextStyle(
                color: Colors.blueGrey,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.account_circle),
            title: Text(l10n.settingsUserName),
            subtitle: Text(_userName.isEmpty ? l10n.settingsGuest : _userName),
            trailing: const Icon(Icons.edit, size: 20),
            onTap: _updateUserName,
          ),
          ListTile(
            leading: const Icon(Icons.group_add),
            title: Text(l10n.settingsJoinTrip),
            subtitle: Text(l10n.settingsJoinTripDescription),
            trailing: const Icon(Icons.chevron_right),
            onTap: _showJoinTripDialog,
          ),
          if (kDebugMode) ...[
            const Divider(),
            ExpansionTile(
              leading: const Icon(Icons.developer_mode),
              title: Text(l10n.settingsAdminMenu),
              childrenPadding: const EdgeInsets.only(bottom: 8),
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      l10n.settingsManualLocation,
                      style: const TextStyle(
                        color: Colors.blueGrey,
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      PlaceField(
                        label: l10n.settingsSearchLocation,
                        value: _manualLocationInput,
                        displayValue: _manualLocationInput,
                        onChanged: _updateManualLocation,
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              manualOverride != null
                                  ? l10n.settingsCurrentCoordinates(
                                      manualOverride.latitude.toStringAsFixed(5),
                                      manualOverride.longitude.toStringAsFixed(5),
                                    )
                                  : l10n.settingsUsingGps,
                            ),
                          ),
                          TextButton(
                            onPressed: manualOverride != null
                                ? _clearManualLocation
                                : null,
                            child: Text(l10n.settingsResetGps),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(
                    Icons.access_time,
                    color: Colors.orange,
                  ),
                  title: Text(l10n.settingsTimeOffset),
                  subtitle: Text(
                    currentOffset == Duration.zero
                        ? l10n.settingsNoTimeOffset(
                            _formatTime(simulatedTime),
                          )
                        : l10n.settingsTimeOffsetSummary(
                            currentOffset.inHours.toString(),
                            currentOffset.inMinutes
                                .remainder(60)
                                .toString(),
                            _formatTime(simulatedTime),
                          ),
                  ),
                  onTap: _updateTimeOffset,
                ),
                ListTile(
                  leading: const Icon(
                    Icons.bug_report,
                    color: Colors.purple,
                  ),
                  title: Text(l10n.settingsCreateDebugTrip),
                  subtitle: Text(l10n.settingsDebugTripDescription),
                  onTap: _createDebugTrip,
                ),
                ListTile(
                  leading: const Icon(
                    Icons.delete_forever,
                    color: Colors.red,
                  ),
                  title: Text(l10n.settingsDeleteAllTrips),
                  subtitle: Text(l10n.settingsDeleteAllTripsDescription),
                  onTap: _deleteAllTrips,
                ),
                ListTile(
                  leading: const Icon(
                    Icons.star,
                    color: Colors.green,
                  ),
                  title: Text(l10n.settingsOpenAsLeader),
                  subtitle: Text(l10n.settingsOpenAsLeaderDescription),
                  onTap: _openLatestTripAsLeader,
                ),
                ListTile(
                  leading: const Icon(
                    Icons.description,
                    color: Colors.blueGrey,
                  ),
                  title: Text(l10n.settingsTripReports),
                  subtitle: Text(l10n.settingsTripReportsDescription),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const TripListPage(),
                      ),
                    );
                  },
                ),
              ],
            ),
          ],

          // 下部に余白を追加
          const SizedBox(height: 40),
        ],
      ),
    );
  }
}
