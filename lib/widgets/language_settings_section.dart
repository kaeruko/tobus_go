import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/locale_provider.dart';

class LanguageSettingsSection extends ConsumerStatefulWidget {
  const LanguageSettingsSection({super.key});

  @override
  ConsumerState<LanguageSettingsSection> createState() =>
      _LanguageSettingsSectionState();
}

class _LanguageSettingsSectionState
    extends ConsumerState<LanguageSettingsSection> {
  bool _saving = false;
  Object? _error;

  Future<void> _select(String? code) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(localeProvider.notifier)
          .setLocale(code == null ? null : Locale(code));
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final preference = ref.watch(localeProvider);
    final selected = preference.valueOrNull?.languageCode;
    final labels = <String?, String>{
      null: l10n.languageSystem,
      'ja': '日本語',
      'en': 'English',
      'zh': '简体中文',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CupertinoListSection(
          header: Text(l10n.languageSettingsTitle),
          children: [
            for (final entry in labels.entries)
              CupertinoListTile(
                title: Text(entry.value),
                trailing: selected == entry.key
                    ? const Icon(CupertinoIcons.check_mark)
                    : null,
                onTap: _saving || preference.isLoading
                    ? null
                    : () => _select(entry.key),
              ),
          ],
        ),
        if (_error != null || preference.hasError)
          Text(
            l10n.languageSaveFailed('${_error ?? preference.error}'),
            style: const TextStyle(color: CupertinoColors.destructiveRed),
          ),
      ],
    );
  }
}
