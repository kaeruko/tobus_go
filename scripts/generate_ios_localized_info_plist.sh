#!/bin/sh
set -eu

: "${TARGET_BUILD_DIR:?TARGET_BUILD_DIR is required}"
: "${WRAPPER_NAME:?WRAPPER_NAME is required}"
: "${APP_CITY:?APP_CITY is required}"

case "$APP_CITY" in
  tokyo)
    display_name="Toei GO"
    ;;
  nagoya)
    display_name="Nagoya GO"
    ;;
  sendai)
    display_name="Sendai GO"
    ;;
  yokohama)
    display_name="Yokohama GO"
    ;;
  *)
    echo "error: unsupported APP_CITY for localized InfoPlist.strings: $APP_CITY" >&2
    exit 1
    ;;
esac

output_dir="$TARGET_BUILD_DIR/$WRAPPER_NAME/en.lproj"
output_file="$output_dir/InfoPlist.strings"
mkdir -p "$output_dir"

cat > "$output_file" <<EOF
"CFBundleDisplayName" = "$display_name";
"NSLocationWhenInUseUsageDescription" = "Used to show your current location on the map.";
EOF

test -s "$output_file"
