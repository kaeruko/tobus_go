import '../models/route_models.dart';

// 簡易的なグローバル保存領域 (メモリのみ)
final List<Candidate> kSavedRoutes = [];

// ★追加: 現在参加中のグループID(nullなら一人モード)
String? kCurrentGroupId;
