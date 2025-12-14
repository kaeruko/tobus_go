import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/user_service.dart';

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
    // 1. UserService (Singleton) Initialization
    final userService = UserService();
    await userService.initialize();
    final userId = userService.currentUserId;
    final userName = await userService.getUserName();

    // 2. SharedPreferences Loading
    final prefs = await SharedPreferences.getInstance();
    final isMemberMode = prefs.getBool(_keyIsMemberMode) ?? false;
    final groupId = prefs.getString(_keyGroupId);

    state = AppSession(
      userId: userId,
      userName: userName,
      appMode: isMemberMode ? AppMode.member : AppMode.normal,
      currentTripId: groupId,
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
