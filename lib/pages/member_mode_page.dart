import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart'; // For sendSOS
import '../models/group_models.dart';
import 'schedule_page.dart';
import '../logic/trip_navigator.dart';
import '../providers/app_session_provider.dart';
import '../providers/trip_provider.dart';
import '../providers/location_provider.dart';
import '../providers/member_nav_progress_provider.dart';


class MemberModePage extends ConsumerStatefulWidget {
  const MemberModePage({super.key});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  // Service for SOS only, data is via provider
  final _tripService = TripService();
  
  @override
  void initState() {
    super.initState();
    
    // Use ref.listen for side-effects (Riverpod-native way)
    ref.listen(tripStreamProvider, (prev, next) {
       next.whenData((trip) {
         if (trip != null) {
           final posAsync = ref.read(locationStreamProvider);
           if (posAsync.hasValue) {
              final pos = posAsync.value!;
              ref.read(memberNavProgressProvider.notifier).updateProgress(trip, LatLng(pos.latitude, pos.longitude));
           }
         }
       });
    });

    ref.listen(locationStreamProvider, (prev, next) {
       next.whenData((pos) {
         final tripAsync = ref.read(tripStreamProvider);
         if (tripAsync.hasValue && tripAsync.value != null) {
            ref.read(memberNavProgressProvider.notifier).updateProgress(tripAsync.value!, LatLng(pos.latitude, pos.longitude));
         }
       });
    });
  }

  Future<void> _leaveGroup() async {
    await ref.read(appSessionProvider.notifier).leaveMemberMode();
    // RootGate will handle the switch
  }

  void _openSchedule(String tripId, List<ScheduleEntry> schedule) {
    Navigator.of(context, rootNavigator: true).push(
      CupertinoPageRoute(
        builder: (_) => SchedulePage(
          tripId: tripId,
          isLeader: false,
          initialSchedule: schedule,
        ),
      ),
    );
  }

  Future<void> _sendSOS(String tripId) async {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('SOS'),
        content: const Text('引率者に通知を送りますか?'),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () async {
              Navigator.pop(ctx);
              await _tripService.sendSOS(tripId);

              if (mounted) {
                showCupertinoDialog(
                  context: context,
                  builder: (ctx2) => CupertinoAlertDialog(
                    content: const Text('引率者に通知しました!'),
                    actions: [
                       CupertinoDialogAction(
                         child: const Text('OK'),
                         onPressed: () => Navigator.pop(ctx2),
                       ),
                    ],
                  ),
                );
              }
            },
            child: const Text('通知する'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Listeners are now in initState
    
    final tripAsync = ref.watch(tripStreamProvider);
    final locationAsync = ref.watch(locationStreamProvider);
    final navProgress = ref.watch(memberNavProgressProvider);

    return tripAsync.when(
      loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (err, stack) => Scaffold(
        appBar: const CupertinoNavigationBar(middle: Text('エラー')),
        body: Center(child: Text('エラー: $err')),
      ),
      data: (trip) {
        if (trip == null) {
          return const Scaffold(
            appBar: CupertinoNavigationBar(middle: Text('エラー')),
            body: Center(child: Text('グループが見つかりません')),
          );
        }

        if (trip.status == TripStatus.cancelled) {
          return Scaffold(
             appBar: AppBar(title: const Text('お知らせ'), backgroundColor: Colors.red),
             body: Center(
               child: Column(
                 mainAxisAlignment: MainAxisAlignment.center,
                 children: [
                   const Text('ホストによりグループが解散されました。', style: TextStyle(fontSize: 18)),
                   const SizedBox(height: 20),
                   ElevatedButton(
                     onPressed: _leaveGroup,
                     child: const Text('OK'),
                   ),
                 ],
               ),
             ),
          );
        }

        final schedule = trip.schedule;
        final currentPos = locationAsync.value != null 
            ? LatLng(locationAsync.value!.latitude, locationAsync.value!.longitude)
            : const LatLng(35.6812, 139.7671); // Default Tokyo Station if waiting for GPS

        // Calculate view state using CURRENT progress indices
        final navState = TripNavigator.updateState(
          trip,
          currentPos,
          navProgress.currentStepIndex,
          navProgress.nextStopIndex,
        );

        return Scaffold(
          backgroundColor: navState.color,
          appBar: AppBar(
            title: const Text('えんそくモード', style: TextStyle(color: Colors.black)),
            backgroundColor: navState.color,
            elevation: 0,
            iconTheme: const IconThemeData(color: Colors.black),
            leading: IconButton(
              icon: const Icon(CupertinoIcons.list_bullet),
              onPressed: () => _openSchedule(trip.id, schedule),
            ),
            actions: [
              TextButton(
                onPressed: () => showCupertinoDialog(
                   context: context,
                   builder: (ctx) => CupertinoAlertDialog(
                     title: const Text('モード終了'),
                     content: const Text('通常モードに戻りますか?'),
                     actions: [
                       CupertinoDialogAction(
                         child: const Text('いいえ'),
                         onPressed: () => Navigator.pop(ctx),
                       ),
                       CupertinoDialogAction(
                         isDestructiveAction: true,
                         child: const Text('はい'),
                         onPressed: () {
                           Navigator.pop(ctx);
                           _leaveGroup();
                         },
                       ),
                     ],
                   ),
                ),
                child: const Text('終了', style: TextStyle(color: CupertinoColors.destructiveRed)),
              ),
            ],
          ),
          body: Center(
             child: Column(
               mainAxisAlignment: MainAxisAlignment.center,
               children: [
                 Text(
                   navState.subText,
                   style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                 ),
                 const SizedBox(height: 20),
                 Text(
                   navState.mainText,
                   style: const TextStyle(
                     fontSize: 48, 
                     fontWeight: FontWeight.bold,
                     color: Colors.white,
                     shadows: [Shadow(blurRadius: 4, color: Colors.black26, offset: Offset(2, 2))],
                   ),
                 ),
           
                 const SizedBox(height: 50),
           
                 GestureDetector(
                   onTap: () => _sendSOS(trip.id),
                   child: Container(
                     width: 150,
                     height: 150,
                     decoration: const BoxDecoration(
                       color: CupertinoColors.systemRed,
                       shape: BoxShape.circle,
                       boxShadow: [
                         BoxShadow(
                           color: Color(0x42000000), 
                           blurRadius: 10,
                           offset: Offset(0, 4),
                         )
                       ]
                     ),
                     child: const Column(
                       mainAxisAlignment: MainAxisAlignment.center,
                       children: [
                         Icon(CupertinoIcons.speaker_2_fill, size: 50, color: CupertinoColors.white),
                         Text(
                           "たすけて",
                           style: TextStyle(
                             color: CupertinoColors.white,
                             fontWeight: FontWeight.bold,
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
      },
    );
  }
}