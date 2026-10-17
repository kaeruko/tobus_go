import 'package:flutter/material.dart';
import '../models/sendai_practical_models.dart';
import '../services/sendai_practical_service.dart';

/// Opt-in test page; not linked from the released application's navigation.
class SendaiPracticalTestPage extends StatefulWidget {
  final SendaiPracticalService service;
  /// Embedded only behind the Sendai debug/local endpoint guard.
  final bool embedded;
  const SendaiPracticalTestPage({super.key, required this.service, this.embedded = false});
  @override
  State<SendaiPracticalTestPage> createState() => _SendaiPracticalTestPageState();
}

class _SendaiPracticalTestPageState extends State<SendaiPracticalTestPage> {
  late final Future<SendaiPracticalCapabilities> _capabilities;
  final _time = TextEditingController(text: '10:00');
  final _directDate = TextEditingController();
  String? _origin, _destination, _date, _pass;
  bool _accept = false, _busy = false;
  String? _error;
  List<SendaiPracticalCandidate>? _results;

  @override
  void initState() {
    super.initState();
    _capabilities = widget.service.capabilities();
  }
  @override
  void dispose() { _time.dispose(); _directDate.dispose(); super.dispose(); }

  Future<void> _search() async {
    final parts = _time.text.split(':');
    final hour = parts.length == 2 ? int.tryParse(parts[0]) : null;
    final minute = parts.length == 2 ? int.tryParse(parts[1]) : null;
    final missing = <String>[
      if (_origin == null) '出発地',
      if (_destination == null) '目的地',
      if (_date == null) '対応日（未確認日を含む）',
      if (_pass == null) '乗車証',
      if (!_accept) '検証用乗換仮設定の同意',
      if (hour == null || minute == null || hour < 0 || hour > 23 ||
          minute < 0 || minute > 59) '出発時刻 HH:MM',
    ];
    if (missing.isNotEmpty) {
      setState(() { _error = '入力不足: ${missing.join('・')}'; _results = null; });
      return;
    }
    setState(() { _busy = true; _error = null; _results = null; });
    try {
      final results = await widget.service.search(originStopId: _origin!,
          destinationStopId: _destination!, civilDate: _date!,
          departureMinute: hour * 60 + minute, farePolicyId: _pass!,
          acceptExperimentalTransfers: _accept);
      if (mounted) setState(() => _results = results);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = FutureBuilder<SendaiPracticalCapabilities>(
      future: _capabilities, builder: (context, snapshot) {
      if (snapshot.hasError) return Text('データを確認できません: ${snapshot.error}');
      if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
      final cap = snapshot.data!;
      String name(String id) => cap.stops.firstWhere((s) => s.id == id).name;
      Widget stopField(String label, String field, String? value, void Function(String?) change) =>
          DropdownButtonFormField<String>(key: Key('sendai-$field'), initialValue: value, isExpanded: true,
            decoration: InputDecoration(labelText: label),
            items: cap.stops.map((s) => DropdownMenuItem(key: ValueKey('sendai-$field-item-${s.id}'), value: s.id,
                child: Text('${s.name}（${s.mode == 'bus' ? '市バス' : '地下鉄'}・${s.id.split(':').last}）', maxLines: 1, overflow: TextOverflow.ellipsis))).toList(),
            onChanged: _busy ? null : (v) => setState(() { change(v); _results = null; }));
      return ListView(padding: const EdgeInsets.all(16), children: [
        const Text('通常ダイヤの予定時刻モデル。到着は目安・乗換は保証しません。'),
        Text('確認済み: ${cap.supportedModes.map((m) => m == 'bus' ? '市営バスの限定区間' : '地下鉄').join('・')}'),
        if (cap.coverageLabel != null) Text('対象: ${cap.coverageLabel}'),
        if (cap.dateBoundaryNotice != null) Text(cap.dateBoundaryNotice!),
        if (!cap.supportedModes.contains('bus')) const Text('市営バスはこのデータでは未対応'),
        const Text('宮城交通・未確認の市営区間・特別ダイヤ・Realtimeは未対応'),
        const Text('データ: 仙台市・仙台市交通局 / 公共交通オープンデータセンター / CC BY 4.0'),
        stopField('出発地', 'origin', _origin, (v) => _origin = v),
        stopField('目的地', 'destination', _destination, (v) => _destination = v),
        DropdownButtonFormField<String>(key: const Key('sendai-date'), decoration: const InputDecoration(labelText: '対応日'),
            items: cap.operatingDates.map((d) => DropdownMenuItem(key: ValueKey('sendai-date-item-$d'), value: d, child: Text(d))).toList(),
            onChanged: _busy ? null : (v) => setState(() {
              _date = v;
              _directDate.text = v ?? '';
              _results = null;
            })),
        TextField(
            key: const Key('sendai-date-direct'),
            controller: _directDate,
            enabled: !_busy,
            decoration: InputDecoration(
              labelText: '対応日を直接入力 YYYY-MM-DD',
              helperText: '表示された対応日のみ。未対応日や臨時運行日は検索不可',
              errorText: _directDate.text.isNotEmpty && _date == null
                  ? 'この日付は現在の確認範囲外です' : null,
            ),
            onChanged: _busy ? null : (text) => setState(() {
              _date = cap.operatingDates.contains(text) ? text : null;
              _results = null;
            })),
        TextField(key: const Key('sendai-time'), controller: _time, enabled: !_busy, decoration: const InputDecoration(labelText: '出発時刻 HH:MM')),
        DropdownButtonFormField<String>(key: const Key('sendai-pass'), decoration: const InputDecoration(labelText: '乗車証を明示選択'),
            items: const [DropdownMenuItem(key: ValueKey('sendai-pass-item-sendai_fureai_pass'), value: 'sendai_fureai_pass', child: Text('ふれあい乗車証（有効な証を所持）'))],
            onChanged: _busy ? null : (v) => setState(() { _pass = v; _results = null; })),
        CheckboxListTile(key: const Key('sendai-accept-transfer'), value: _accept, onChanged: _busy ? null : (v) => setState(() { _accept = v ?? false; _results = null; }),
            title: const Text('検証用の乗換仮設定を使用する'),
            subtitle: const Text('仙台の地下鉄間は公式5分＋仮の余裕2分。バス接続は拠点別の仮設定です。実測・正式採用・保証ではありません。')),
        FilledButton(key: const Key('sendai-search'), onPressed: _busy ? null : _search, child: Text(_busy ? '検索中' : '追加支払0円の確認済み区間を検索')),
        if (_error != null) Text(_error!, key: const Key('sendai-test-error')),
        if (_results != null && _results!.isEmpty) const Text('この条件で確認済み経路はありません'),
        for (final route in _results ?? <SendaiPracticalCandidate>[]) Card(key: const Key('sendai-result'), child: Padding(
          padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('追加支払0円・到着目安 ${route.arrival.date} ${route.arrival.time}'),
            for (final event in route.events)
              if (event is SendaiPracticalRide) Text('${event.mode == 'bus' ? '市営バス' : '地下鉄'} ${name(event.fromStopId)} → ${name(event.toStopId)}\n'
                  '${event.mode == 'bus' ? 'GTFS予定発車' : '公式発車時刻'} ${event.departure.time} / '
                  '${event.mode == 'bus' ? 'GTFS予定到着' : '到着目安'} ${event.arrival.date} ${event.arrival.time}')
              else if (event is SendaiPracticalTransfer) Text('${event.timeBasis == 'official_standard' ? '公式標準' : '仮の乗換'}${event.standardMinutes}分＋仮の余裕${event.marginMinutes}分\n${event.pathDescription ?? '仙台駅 地下鉄間'}'),
            const Text('有効な乗車証の所持を前提。通常運賃の設定は変更しません。'),
          ]))),
      ]);
    });
    return widget.embedded ? content : Scaffold(
      appBar: AppBar(title: const Text('仙台でGO 検証用')),
      body: content,
    );
  }
}
