import 'package:cloud_firestore/cloud_firestore.dart';

class GroupService {
  // Firestoreのデータベース本体
  final FirebaseFirestore _db = FirebaseFirestore.instance;

  /// グループを作成する(リーダー用)
  /// groupId: 参加用の4桁コードなど
  /// leaderId: 自分の端末IDなど
  /// routeData: 検索結果のJSONデータ
  Future<void> createGroup(String groupId, String leaderId, Map<String, dynamic> routeData) async {
    // "groups" という箱の中に、groupId の名前で書類を作る
    await _db.collection('groups').doc(groupId).set({
      'leaderId': leaderId,
      'status': 'waiting', // waiting, moving, goal
      'route': routeData,  // 経路情報を丸ごと保存
      'members': [],       // 最初は誰もいない
      'createdAt': FieldValue.serverTimestamp(), // 作成日時
    });
  }

  /// グループに参加する(メンバー用)
  Future<void> joinGroup(String groupId, String memberId, String memberName) async {
    // 既存のメンバーリストに追加する処理
    await _db.collection('groups').doc(groupId).update({
      'members': FieldValue.arrayUnion([
        {'id': memberId, 'name': memberName}
      ]),
    });
  }

  /// グループの情報をリアルタイムで監視する(ストリーム)
  /// 画面側でこれを使うと、DBが更新された瞬間に画面も変わります
  Stream<DocumentSnapshot> streamGroup(String groupId) {
    return _db.collection('groups').doc(groupId).snapshots();
  }
}
