#!/bin/sh
set -eu

: "${TARGET_BUILD_DIR:?TARGET_BUILD_DIR is required}"
: "${WRAPPER_NAME:?WRAPPER_NAME is required}"
: "${APP_CITY:?APP_CITY is required}"

case "$APP_CITY" in
  tokyo)
    display_name_ja="都営でGO"
    display_name_en="Toei GO"
    ;;
  nagoya)
    display_name_ja="名古屋でGO"
    display_name_en="Nagoya GO"
    ;;
  sendai)
    display_name_ja="仙台でGO"
    display_name_en="Sendai GO"
    ;;
  yokohama)
    display_name_ja="横浜でGO"
    display_name_en="Yokohama GO"
    ;;
  *)
    echo "error: unsupported APP_CITY for localized InfoPlist.strings: $APP_CITY" >&2
    exit 1
    ;;
esac

en_output_dir="$TARGET_BUILD_DIR/$WRAPPER_NAME/en.lproj"
en_output_file="$en_output_dir/InfoPlist.strings"
ja_output_dir="$TARGET_BUILD_DIR/$WRAPPER_NAME/ja.lproj"
ja_output_file="$ja_output_dir/InfoPlist.strings"

mkdir -p "$en_output_dir" "$ja_output_dir"

cat > "$en_output_file" <<EOF
"CFBundleDisplayName" = "$display_name_en";
"NSLocationWhenInUseUsageDescription" = "Used to show your current location on the map.";
EOF

cat > "$ja_output_file" <<EOF
"CFBundleDisplayName" = "$display_name_ja";
"NSLocationWhenInUseUsageDescription" = "地図で現在地を表示するために使用します。";
EOF

test -s "$en_output_file"
test -s "$ja_output_file"
