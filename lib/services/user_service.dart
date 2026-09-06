import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class UserService {
  static const String _keyUserId = 'user_uid';
  static const String _keyUserName = 'user_name';
  static const String _keyUserProvisioned = 'user_provisioned_v1';
  static const Duration _firestoreTimeout = Duration(seconds: 15);

  // シングルトンパターン（どこから呼んでも同じインスタンス）
  static final UserService _instance = UserService._internal();
  factory UserService() => _instance;
  UserService._internal();

  // 現在のユーザーID
  String? _currentUserId;
  String? get currentUserId => _currentUserId;

  Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    final storedUid = prefs.getString(_keyUserId);
    final uid = storedUid ?? const Uuid().v4();
    final provisioned = prefs.getBool(_keyUserProvisioned) ?? false;

    if (!provisioned) {
      await _ensureRemoteUser(uid, checkExisting: storedUid != null);

      // Firestore側のユーザーを確認できてからローカル状態を確定する。
      // これにより途中失敗でUIDだけが残る不整合を防ぐ。
      await prefs.setString(_keyUserId, uid);
      await prefs.setBool(_keyUserProvisioned, true);
    }

    _currentUserId = uid;
    print('User ID initialized: $_currentUserId');
  }

  Future<void> _ensureRemoteUser(
    String uid, {
    required bool checkExisting,
  }) async {
    final document = FirebaseFirestore.instance.collection('users').doc(uid);

    if (checkExisting) {
      final snapshot = await document
          .get(const GetOptions(source: Source.server))
          .timeout(_firestoreTimeout);
      if (snapshot.exists) {
        return;
      }
    }

    await document.set({
      'createdAt': FieldValue.serverTimestamp(),
      'displayName': 'ゲスト',
      'isStaffMode': false,
    }).timeout(_firestoreTimeout);
  }

  // ユーザー名の取得
  Future<String> getUserName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyUserName) ?? 'ゲスト';
  }

  // ユーザー名の更新
  Future<void> updateUserName(String name) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyUserName, name);

    if (_currentUserId != null) {
      await FirebaseFirestore.instance.collection('users').doc(_currentUserId).set({
        'displayName': name,
      }, SetOptions(merge: true));
    }
  }
}
