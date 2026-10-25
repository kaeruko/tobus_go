import 'package:flutter/cupertino.dart';

import '../l10n/app_localizations.dart';

class EstimatedTransferSearchControl extends StatelessWidget {
  const EstimatedTransferSearchControl({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Semantics(
      label: l10n.includeEstimatedTransferRoutes,
      toggled: value,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    l10n.includeEstimatedTransferRoutes,
                    key: const Key('estimated-transfer-option-label'),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                const SizedBox(width: 8),
                CupertinoSwitch(
                  key: const Key('estimated-transfer-option-switch'),
                  value: value,
                  onChanged: onChanged,
                ),
              ],
            ),
            if (value) ...[
              const SizedBox(height: 8),
              Text(
                l10n.estimatedTransferRouteDescription,
                key: const Key('estimated-transfer-option-description'),
                style: const TextStyle(
                  color: CupertinoColors.systemGrey,
                  fontSize: 12,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class EstimatedTransferWarning extends StatelessWidget {
  const EstimatedTransferWarning({super.key, this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Container(
      padding: EdgeInsets.all(compact ? 10 : 12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemOrange.withValues(alpha: 0.12),
        border: Border.all(
          color: CupertinoColors.systemOrange.withValues(alpha: 0.5),
        ),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            l10n.estimatedTransferRouteLabel,
            style: const TextStyle(
              color: CupertinoColors.systemOrange,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            l10n.estimatedTransferRouteDescription,
            style: TextStyle(
              color: CupertinoColors.label,
              fontSize: compact ? 11 : 13,
            ),
          ),
        ],
      ),
    );
  }
}
