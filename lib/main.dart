import 'package:flutter/cupertino.dart';
import 'pages/root_tabs.dart';

import 'services/storage_service.dart';
import 'data/global_state.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
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
      home: RootTabs(),
    );
  }
}
