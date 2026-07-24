#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift build -c release
APP=".build/Trunkline.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 아이콘 빌드: SVG → iconset → icns. 실패해도 경고만 출력하고 패키징 계속.
SVG="Assets/icon-app.svg"
ICON_TAG=""
if command -v qlmanage >/dev/null && command -v sips >/dev/null && command -v iconutil >/dev/null; then
    ICON_TMP="$(mktemp -d)"
    trap 'rm -rf "$ICON_TMP"' EXIT
    if qlmanage -t -s 1024 -o "$ICON_TMP" "$SVG" >/dev/null 2>&1 && [ -f "$ICON_TMP/icon-app.svg.png" ]; then
        ICONSET="$ICON_TMP/Trunkline.iconset"
        mkdir -p "$ICONSET"
        specs=("16:icon_16x16.png" "32:icon_16x16@2x.png" "32:icon_32x32.png" "64:icon_32x32@2x.png"
               "128:icon_128x128.png" "256:icon_128x128@2x.png" "256:icon_256x256.png"
               "512:icon_256x256@2x.png" "512:icon_512x512.png" "1024:icon_512x512@2x.png")
        icon_ok=true
        for spec in "${specs[@]}"; do
            size="${spec%%:*}"; name="${spec##*:}"
            sips -z "$size" "$size" "$ICON_TMP/icon-app.svg.png" --out "$ICONSET/$name" >/dev/null 2>&1 || icon_ok=false
        done
        if $icon_ok && iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Trunkline.icns" >/dev/null 2>&1; then
            ICON_TAG="  <key>CFBundleIconFile</key><string>Trunkline</string>"
        else
            echo "warning: icns 생성 실패 — 아이콘 없이 패키징 계속" >&2
        fi
    else
        echo "warning: SVG → PNG 변환 실패(qlmanage) — 아이콘 없이 패키징 계속" >&2
    fi
else
    echo "warning: qlmanage/sips/iconutil 없음 — 아이콘 없이 패키징 계속" >&2
fi

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>io.github.kilhyeonjun.trunkline</string>
  <key>CFBundleName</key><string>Trunkline</string>
  <key>CFBundleExecutable</key><string>Trunkline</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
$ICON_TAG
</dict></plist>
EOF
cp .build/release/Trunkline "$APP/Contents/MacOS/"
codesign --force --sign - "$APP"
xattr -cr "$APP"
echo "packaged: $APP"
