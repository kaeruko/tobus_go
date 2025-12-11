import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

class UserService {
  static const String _keyUserId = 'user_uid';
  static const String _keyUserName = 'user_name';

  // シングルトンパターン（どこから呼んでも同じインスタンス）
  static final UserService _instance = UserService._internal();
  factory UserService() => _instance;
  UserService._internal();

  // 現在のユーザーID
  String? _currentUserId;
  String? get currentUserId => _currentUserId;

  // 初期化：IDを取得、なければ生成して保存
  Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    String? uid = prefs.getString(_keyUserId);

    if (uid == null) {
      // 初回起動：ID生成
      uid = const Uuid().v4();
      await prefs.setString(_keyUserId, uid);
      
      // Firestoreにユーザー情報を作成
      await FirebaseFirestore.instance.collection('users').doc(uid).set({
        'createdAt': FieldValue.serverTimestamp(),
        'displayName': 'ゲスト', // 初期名
        'isStaffMode': false,   // デフォルトは一般モード
      });
    }
    
    _currentUserId = uid;
    print("User ID initialized: $_currentUserId");
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
      await FirebaseFirestore.instance.collection('users').doc(_currentUserId).update({
        'displayName': name,
      });
    }
  }
}
