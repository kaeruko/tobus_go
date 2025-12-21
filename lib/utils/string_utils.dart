class StringUtils {
  static String extractSimpleName(String fullName) {
    if (fullName.isEmpty) return fullName;
    return fullName.split(RegExp(r'[\s　]+')).last;
  }
}
