import 'package:flutter/cupertino.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/app_localizations.dart';

class ForceUpdatePage extends StatefulWidget {
  final String messageJa;
  final String messageEn;
  final String currentVersion;
  final String minimumVersion;
  final Uri? storeUri;

  const ForceUpdatePage({
    super.key,
    required this.messageJa,
    required this.messageEn,
    required this.currentVersion,
    required this.minimumVersion,
    required this.storeUri,
  });

  @override
  State<ForceUpdatePage> createState() => _ForceUpdatePageState();
}

class _ForceUpdatePageState extends State<ForceUpdatePage> {
  bool _openingStore = false;

  Future<void> _openStore() async {
    final storeUri = widget.storeUri;
    if (storeUri == null) {
      throw StateError(
        'Force update is active but no store URL is configured for this platform.',
      );
    }
    if (_openingStore) return;

    setState(() => _openingStore = true);
    try {
      final launched = await launchUrl(
        storeUri,
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        throw StateError('Failed to open update store URL: $storeUri');
      }
    } finally {
      if (mounted) {
        setState(() => _openingStore = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final languageCode = Localizations.localeOf(context).languageCode;
    final message = languageCode == 'ja'
        ? widget.messageJa
        : widget.messageEn;

    return CupertinoPageScaffold(
      child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    CupertinoIcons.arrow_down_circle_fill,
                    size: 64,
                    color: CupertinoColors.activeBlue,
                  ),
                  const SizedBox(height: 20),
                  Text(
                    l10n.updateRequiredTitle,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    message,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 17, height: 1.45),
                  ),
                  const SizedBox(height: 18),
                  Text(
                    l10n.currentVersionLabel(widget.currentVersion),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 14,
                      color: CupertinoColors.secondaryLabel,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    l10n.minimumVersionLabel(widget.minimumVersion),
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 14,
                      color: CupertinoColors.secondaryLabel,
                    ),
                  ),
                  const SizedBox(height: 24),
                  if (widget.storeUri != null)
                    SizedBox(
                      width: double.infinity,
                      child: CupertinoButton.filled(
                        onPressed: _openingStore ? null : _openStore,
                        child: _openingStore
                            ? const CupertinoActivityIndicator(
                                color: CupertinoColors.white,
                              )
                            : Text(l10n.updateNow),
                      ),
                    )
                  else
                    Text(
                      l10n.updateStoreUnavailable,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 15,
                        color: CupertinoColors.secondaryLabel,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
