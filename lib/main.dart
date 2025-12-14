import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart'; // MaterialLocalizationsのために必要
import 'package:flutter_localizations/flutter_localizations.dart'; // 追加
import 'package:shared_preferences/shared_preferences.dart'; // ★追加
import 'pages/root_tabs.dart';
import 'pages/member_mode_page.dart'; // ★追加

import 'services/storage_service.dart';
import 'services/user_service.dart'; // ★追加
import 'data/global_state.dart';

// ★追加1: Firebase関連のインポート
import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart'; // 自動生成されたファイル

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // ★追加2: Firebaseを初期化(今の機種に合わせた設定で起動)
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  
  // 保存された経路を読み込む
  final storage = StorageService();
  final saved = await storage.loadRoutes();
  kSavedRoutes.addAll(saved);

  // ★起動時にモード判定
  final prefs = await SharedPreferences.getInstance();
  kCurrentGroupId = prefs.getString('groupId');
  kIsMemberMode = prefs.getBool('isMemberMode') ?? false;

  // ★ユーザーIDの初期化 (これをしないとIDがnullになる)
  await UserService().initialize();

  runApp(const App());
}

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) {
    return CupertinoApp(
      debugShowCheckedModeBanner: false,
      title: '都営でGO',
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [
        Locale('ja', 'JP'),
      ],
      builder: (context, child) => ScaffoldMessenger(child: child!),
      // ★ここで分岐!
      home: kIsMemberMode ? const MemberModePage() : const RootTabs(),
    );
  }
}
