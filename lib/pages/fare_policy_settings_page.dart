import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/city_profile.dart';
import '../providers/city_profile_provider.dart';
import '../services/fare_policy_preferences.dart';
import 'settings_page.dart';

class FarePolicySettingsPage extends ConsumerStatefulWidget {
  const FarePolicySettingsPage({super.key});

  @override
  ConsumerState<FarePolicySettingsPage> createState() =>
      _FarePolicySettingsPageState();
}

class _FarePolicySettingsPageState
    extends ConsumerState<FarePolicySettingsPage> {
  String? _selectedPolicyId;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    final profile = ref.read(cityProfileProvider);
    try {
      final selected = await FarePolicyPreferences.load(profile);
      if (!mounted) return;
      setState(() {
        _selectedPolicyId = selected;
        _loading = false;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  Future<void> _select(CityProfile profile, String policyId) async {
    try {
      await FarePolicyPreferences.save(profile, policyId);
      if (!mounted) return;
      setState(() {
        _selectedPolicyId = policyId;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    }
  }

  Future<void> _openSource(String sourceUri) async {
    final uri = Uri.parse(sourceUri);
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok) {
      throw StateError('制度の公式ページを開けませんでした: $sourceUri');
    }
  }

  String _settlementLabel(String type) {
    switch (type) {
      case 'normal':
        return '通常払い';
      case 'discount':
        return '割引';
      case 'free_pass':
        return '無料乗車証';
      case 'reimbursement':
        return 'いったん支払い・後日支給';
      default:
        throw StateError('Unsupported settlement type: $type');
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(cityProfileProvider);

    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('設定')),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          children: [
            const Text(
              '運賃・乗車証',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              '利用する制度や所持乗車証を自分で選択します。住所・障害区分・年齢などから資格を自動判定しません。',
              style: TextStyle(color: CupertinoColors.systemGrey),
            ),
            const SizedBox(height: 16),
            if (_loading)
              const Center(child: CupertinoActivityIndicator())
            else if (_error != null)
              Text(
                '設定エラー: $_error',
                style: const TextStyle(
                  color: CupertinoColors.destructiveRed,
                ),
              )
            else
              ...profile.farePolicies.map(
                (option) => _PolicyCard(
                  option: option,
                  selected: option.id == _selectedPolicyId,
                  settlementLabel: _settlementLabel(option.settlementType),
                  onSelect: () => _select(profile, option.id),
                  onSource: option.sourceUri == null
                      ? null
                      : () => _openSource(option.sourceUri!),
                ),
              ),
            if (!profile.capabilities.features.routeSearchOnly) ...[
              const SizedBox(height: 24),
              CupertinoButton(
                onPressed: () {
                  Navigator.of(context).push(
                    CupertinoPageRoute(builder: (_) => const SettingsPage()),
                  );
                },
                child: const Text('その他の設定を開く'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PolicyCard extends StatelessWidget {
  final FarePolicyOption option;
  final bool selected;
  final String settlementLabel;
  final VoidCallback onSelect;
  final VoidCallback? onSource;

  const _PolicyCard({
    required this.option,
    required this.selected,
    required this.settlementLabel,
    required this.onSelect,
    required this.onSource,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        decoration: BoxDecoration(
          border: Border.all(
            color: selected
                ? CupertinoColors.activeBlue
                : CupertinoColors.separator.resolveFrom(context),
            width: selected ? 2 : 1,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: CupertinoButton(
          padding: const EdgeInsets.all(14),
          onPressed: onSelect,
          child: Row(
            children: [
              Icon(
                selected
                    ? CupertinoIcons.check_mark_circled_solid
                    : CupertinoIcons.circle,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      option.displayName,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      settlementLabel,
                      style: const TextStyle(
                        fontSize: 13,
                        color: CupertinoColors.systemGrey,
                      ),
                    ),
                    if (onSource != null)
                      GestureDetector(
                        onTap: onSource,
                        child: const Padding(
                          padding: EdgeInsets.only(top: 5),
                          child: Text(
                            '公式情報を確認',
                            style: TextStyle(
                              fontSize: 13,
                              color: CupertinoColors.activeBlue,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
