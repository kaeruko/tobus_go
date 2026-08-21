class FareQuote {
  final int? normalFareYen;
  final int? payNowYen;
  final int? effectiveFareYen;
  final String policyId;
  final String settlementType;
  final String status;
  final String? unavailableReason;

  const FareQuote({
    required this.normalFareYen,
    required this.payNowYen,
    required this.effectiveFareYen,
    required this.policyId,
    required this.settlementType,
    required this.status,
    this.unavailableReason,
  });

  factory FareQuote.fromJson(Map<String, dynamic> json) {
    final policyId = json['policyId']?.toString() ?? '';
    final settlementType = json['settlementType']?.toString() ?? '';
    final status = json['status']?.toString() ?? '';
    if (policyId.isEmpty) {
      throw const FormatException('fare quote is missing policyId');
    }
    const settlements = {
      'normal',
      'discount',
      'free_pass',
      'reimbursement',
    };
    if (!settlements.contains(settlementType)) {
      throw FormatException('unsupported fare settlementType: $settlementType');
    }
    if (status != 'available' && status != 'unavailable') {
      throw FormatException('unsupported fare status: $status');
    }
    final reason = json['unavailableReason']?.toString();
    if (status == 'unavailable' && (reason == null || reason.isEmpty)) {
      throw const FormatException(
        'unavailable fare quote is missing unavailableReason',
      );
    }
    return FareQuote(
      normalFareYen: (json['normalFareYen'] as num?)?.toInt(),
      payNowYen: (json['payNowYen'] as num?)?.toInt(),
      effectiveFareYen: (json['effectiveFareYen'] as num?)?.toInt(),
      policyId: policyId,
      settlementType: settlementType,
      status: status,
      unavailableReason: reason,
    );
  }

  bool get isAvailable => status == 'available';

  String get settlementLabel {
    switch (settlementType) {
      case 'normal':
        return '通常払い';
      case 'discount':
        return '割引';
      case 'free_pass':
        return '無料乗車証';
      case 'reimbursement':
        return '後日支給';
      default:
        throw StateError('Unsupported settlementType: $settlementType');
    }
  }
}
