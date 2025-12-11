import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart'; // MaterialLocalizationsのために必要
import 'package:flutter_localizations/flutter_localizations.dart'; // 追加
import 'pages/root_tabs.dart';

import 'services/storage_service.dart';
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

  runApp(const App());
}

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) {
    return const CupertinoApp(
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
      home: RootTabs(),
    );
  }
}
