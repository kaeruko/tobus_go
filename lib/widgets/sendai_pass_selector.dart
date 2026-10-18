import 'package:flutter/cupertino.dart';

import '../core/city_profile.dart';
import '../services/fare_policy_preferences.dart';

/// Explicit user selection of an already-held Sendai transit card.
///
/// The two cards use the same reviewed bus/subway routing network. Senior
/// card balance debits are never represented as free or computed here.
class SendaiPassSelector extends StatefulWidget {
  const SendaiPassSelector({super.key, required this.onSelectionChanged});

  final VoidCallback onSelectionChanged;

  @override
  State<SendaiPassSelector> createState() => _SendaiPassSelectorState();
}

class _SendaiPassSelectorState extends State<SendaiPassSelector> {
  String? _selected;
  String? _error;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    try {
      final saved = await FarePolicyPreferences.load(sendaiCityProfile);
      if (!mounted) return;
      setState(() {
        // An old 'normal' preference is not evidence of pass ownership.
        _selected = saved == 'sendai_fureai_pass' ||
                saved == 'sendai_keiro_pass'
            ? saved
            : null;
        _busy = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.toString();
      });
    }
  }

  Future<void> _choose(String? id) async {
    if (_busy || id == null ||
        (id != 'sendai_fureai_pass' && id != 'sendai_keiro_pass')) {
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await FarePolicyPreferences.save(sendaiCityProfile, id);
      if (!mounted) return;
      setState(() { _selected = id; _busy = false; });
      widget.onSelectionChanged();
    } catch (error) {
      if (!mounted) return;
      setState(() { _busy = false; _error = error.toString(); });
    }
  }

  @override
  Widget build(BuildContext context) {
    final japanese = Localizations.localeOf(context).languageCode == 'ja';
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CupertinoSlidingSegmentedControl<String>(
          key: const Key('sendai-pass-selector'),
          groupValue: _selected,
          children: {
            'sendai_fureai_pass': Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              child: Text(japanese ? 'ふれあい' : 'Fureai'),
            ),
            'sendai_keiro_pass': Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              child: Text(japanese ? '敬老' : 'Senior'),
            ),
          },
          onValueChanged: (id) {
            if (!_busy) _choose(id);
          },
        ),
        if (_error != null)
          Text(_error!, style: const TextStyle(color: CupertinoColors.destructiveRed)),
      ],
    );
  }
}
