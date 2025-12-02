import 'package:flutter/cupertino.dart';
import 'pages/root_tabs.dart';

void main() => runApp(const App());

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
