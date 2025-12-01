import 'package:flutter/cupertino.dart';

class LivePage extends StatelessWidget {
  const LivePage({super.key});
  @override
  Widget build(BuildContext context) {
    return const CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(middle: Text('ライブ')),
      child: SafeArea(child: _LiveContent()),
    );
  }
}

class _LiveContent extends StatefulWidget {
  const _LiveContent();
  @override
  State<_LiveContent> createState() => _LiveContentState();
}

class _LiveContentState extends State<_LiveContent> {
  int tab = 0; // 0: バス停, 1: 駅
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16.0),
          child: CupertinoSlidingSegmentedControl<int>(
            groupValue: tab,
            children: const {0: Text('バス停'), 1: Text('駅')},
            onValueChanged: (v) => setState(() => tab = v ?? 0),
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            itemBuilder: (_, i) => _liveRow(i),
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemCount: 12,
          ),
        ),
      ],
    );
  }

  Widget _liveRow(int i) {
    return Container(
      decoration: BoxDecoration(
        color: CupertinoColors.systemGrey6,
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(12),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: CupertinoColors.activeBlue,
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Text(
              '上23',
              style: TextStyle(color: CupertinoColors.white),
            ),
          ),
          const SizedBox(width: 8),
          const Expanded(child: Text('平井七丁目北公園前 → 上野松坂屋前')),
          const Text(
            'あと 5 分',
            style: TextStyle(color: CupertinoColors.activeGreen),
          ),
        ],
      ),
    );
  }
}
