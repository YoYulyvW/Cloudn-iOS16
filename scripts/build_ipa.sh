#!/usr/bin/env bash
# 本地一键构建：拉上游最新 -> 应用 iOS 16.4 移植 -> 产出未签名 IPA（需 macOS + Xcode 15+）
set -euo pipefail

UPSTREAM="${UPSTREAM:-https://github.com/mengangs/Cloudn.git}"
WORK="${WORK:-$PWD/upstream-src}"
HERE="$(cd "$(dirname "$0")" && pwd)"

rm -rf "$WORK"
git clone --depth 1 "$UPSTREAM" "$WORK"
python3 "$HERE/port_ios16.py" "$WORK"

cd "$WORK"
xcodebuild -project Cloudn.xcodeproj -scheme Cloudn -configuration Release \
  -destination 'generic/platform=iOS' -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" build

mkdir -p Payload
cp -R build/Build/Products/Release-iphoneos/Cloudn.app Payload/
VERSION="$(grep -m1 'MARKETING_VERSION' Cloudn.xcodeproj/project.pbxproj | sed -E 's/.*= *([^;]+);/\1/')"
IPA="Cloudn-ios16.4-${VERSION}.ipa"
zip -qry "$IPA" Payload
shasum -a 256 "$IPA" | tee SHA256SUMS.txt
echo "完成: $WORK/$IPA"
