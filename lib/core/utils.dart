(String, String)? splitComma(String s) {
  final i = s.indexOf(',');
  if (i <= 0) return null;
  final a = s.substring(0, i).trim();
  final b = s.substring(i + 1).trim();
  if (a.isEmpty || b.isEmpty) return null;
  return (a, b);
}

(double, double)? parseLatLon(String s) {
  var t = s.trim();
  // 全角→半角、全角カンマ対応
  const full2half = {
    '０': '0',
    '１': '1',
    '２': '2',
    '３': '3',
    '４': '4',
    '５': '5',
    '６': '6',
    '７': '7',
    '８': '8',
    '９': '9',
    '－': '-',
    '，': ',',
    '．': '.',
  };
  t = t.split('').map((ch) => full2half[ch] ?? ch).join();
  // 数字・符号・小数点・カンマ以外を除去（カッコなどを消す）
  t = t.replaceAll(RegExp(r'[^\d\.\-\,]'), '');
  final sp = splitComma(t);
  if (sp == null) return null;
  final lat = double.tryParse(sp.$1);
  final lon = double.tryParse(sp.$2);
  if (lat == null || lon == null) return null;
  if (lat.abs() > 90 || lon.abs() > 180) return null;
  return (lat, lon);
}
