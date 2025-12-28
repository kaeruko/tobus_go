import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/user_service.dart';
import '../services/trip_service.dart';
import '../models/trip_models.dart';

enum AppMode { normal, member }

class AppSession {
  final String? userId;
  final String? userName;
  final AppMode appMode;
  final String? currentTripId;

  const AppSession({
    this.userId,
    this.userName,
    this.appMode = AppMode.normal,
    this.currentTripId,
  });

  AppSession copyWith({
    String? userId,
    String? userName,
    AppMode? appMode,
    String? currentTripId,
  }) {
    return AppSession(
      userId: userId ?? this.userId,
      userName: userName ?? this.userName,
      appMode: appMode ?? this.appMode,
      currentTripId: currentTripId ?? this.currentTripId,
    );
  }
  
  bool get isMemberMode => appMode == AppMode.member;
}

class AppSessionNotifier extends StateNotifier<AppSession> {
  AppSessionNotifier() : super(const AppSession());

  static const _keyIsMemberMode = 'isMemberMode';
  static const _keyGroupId = 'groupId';

  Future<void> initialize() async {
    final userService = UserService();
    await userService.initialize();
    final userId = userService.currentUserId;
    final userName = await userService.getUserName();

    final prefs = await SharedPreferences.getInstance();
    final isMemberMode = prefs.getBool(_keyIsMemberMode) ?? false;
    final groupId = prefs.getString(_keyGroupId);

    var mode = isMemberMode ? AppMode.member : AppMode.normal;
    String? tripId = groupId;

    // member true なのに tripId 無しなら矯正
    if (mode == AppMode.member && tripId == null) {
      await prefs.setBool(_keyIsMemberMode, false);
      mode = AppMode.normal;
    }

    // member 復元時のみ trip を検証
    if (mode == AppMode.member && tripId != null) {
      final trip = await TripService().getTrip(tripId);

      final isActiveTrip = trip != null &&
          (trip.travelPhase == TravelPhase.planning ||
              trip.travelPhase == TravelPhase.active);

      final isMember = trip != null &&
          userId != null &&
          trip.memberIds.contains(userId);

      final invalid = !isActiveTrip || !isMember;

      if (invalid) {
        await prefs.remove(_keyGroupId);
        await prefs.setBool(_keyIsMemberMode, false);
        mode = AppMode.normal;
        tripId = null;
      }
    }

    state = AppSession(
      userId: userId,
      userName: userName,
      appMode: mode,
      currentTripId: tripId,
    );
  }

  Future<void> updateMode(AppMode mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_keyIsMemberMode, mode == AppMode.member);
    state = state.copyWith(appMode: mode);
  }

  Future<void> updateTripId(String? tripId) async {
    final prefs = await SharedPreferences.getInstance();
    if (tripId == null) {
      await prefs.remove(_keyGroupId);
    } else {
      await prefs.setString(_keyGroupId, tripId);
    }
    state = state.copyWith(currentTripId: tripId);
  }

  Future<void> enterMemberMode(String tripId) async {
    final prefs = await SharedPreferences.getInstance();
    // Persist changes
    await prefs.setString(_keyGroupId, tripId);
    await prefs.setBool(_keyIsMemberMode, true);
    
    // Atomic state update
    state = state.copyWith(
      currentTripId: tripId,
      appMode: AppMode.member,
    );
  }

  Future<void> leaveMemberMode() async {
    final prefs = await SharedPreferences.getInstance();
    // Persist changes
    await prefs.remove(_keyGroupId);
    await prefs.setBool(_keyIsMemberMode, false);
    
    // Atomic state update
    state = state.copyWith(
      currentTripId: null,
      appMode: AppMode.normal,
    );
  }
}

final appSessionProvider = StateNotifierProvider<AppSessionNotifier, AppSession>((ref) {
  return AppSessionNotifier();
});
