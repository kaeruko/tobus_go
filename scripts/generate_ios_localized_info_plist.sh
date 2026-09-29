#!/bin/sh
set -eu

: "${TARGET_BUILD_DIR:?TARGET_BUILD_DIR is required}"
: "${WRAPPER_NAME:?WRAPPER_NAME is required}"
: "${APP_CITY:?APP_CITY is required}"

case "$APP_CITY" in
  tokyo)
    display_name_ja="都営でGO"
    display_name_en="Toei GO"
    display_name_zh="都营GO"
    ;;
  nagoya)
    display_name_ja="名古屋でGO"
    display_name_en="Nagoya GO"
    display_name_zh="名古屋GO"
    ;;
  sendai)
    display_name_ja="仙台でGO"
    display_name_en="Sendai GO"
    display_name_zh="仙台GO"
    ;;
  yokohama)
    display_name_ja="横浜でGO"
    display_name_en="Yokohama GO"
    display_name_zh="横滨GO"
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

zh_output_dir="$TARGET_BUILD_DIR/$WRAPPER_NAME/zh-Hans.lproj"
zh_output_file="$zh_output_dir/InfoPlist.strings"

mkdir -p "$en_output_dir" "$ja_output_dir" "$zh_output_dir"

cat > "$en_output_file" <<EOF
"CFBundleDisplayName" = "$display_name_en";
"NSLocationWhenInUseUsageDescription" = "Used to show your current location on the map.";
EOF

cat > "$ja_output_file" <<EOF
"CFBundleDisplayName" = "$display_name_ja";
"NSLocationWhenInUseUsageDescription" = "地図で現在地を表示するために使用します。";
EOF

cat > "$zh_output_file" <<EOF
"CFBundleDisplayName" = "$display_name_zh";
"NSLocationWhenInUseUsageDescription" = "用于在地图上显示您的当前位置。";
EOF

test -s "$zh_output_file"
test -s "$en_output_file"
test -s "$ja_output_file"
