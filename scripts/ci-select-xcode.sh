#!/usr/bin/env bash
# Select the newest RELEASED Xcode of one major version on a GitHub-hosted
# macOS runner, or fail. Used by every macOS job of release-ios.yml.
#
# Usage:
#   scripts/ci-select-xcode.sh <major>            # select it (sudo xcode-select -s)
#   scripts/ci-select-xcode.sh <major> --print    # only print the choice
#
# Why not "whatever is newest on the image":
#   * From April 2027 App Store Connect only accepts iOS uploads built with
#     the iOS 27 SDK (upload warning 90725). The job must fail when the wanted
#     Xcode is missing, never fall back to an older one: a failed run publishes
#     nothing, a build with an older SDK is refused at upload.
#   * Betas must be skipped. App Store Connect refuses builds made with one,
#     and the runner image gives a beta a release-looking symlink
#     (Xcode_27.3.app -> Xcode_27.3_beta.app), so every candidate is resolved
#     to its real path first. A candidate counts as a release only when its
#     real name has no beta / release-candidate marker AND licenseType in its
#     LicenseInfo.plist is "GM" (betas say "Beta"). An Xcode with any other
#     licenseType is skipped with a warning, so the next-newest release is used.
#
# On success it exports XCODE_APP, XCODE_VERSION and XCODE_BUILD to later
# steps ($GITHUB_ENV) and sets the step outputs path, version and build.
#
# XCODE_APPS_DIR overrides /Applications (tests with fake layouts).
set -euo pipefail

MAJOR="${1:?usage: $0 <xcode major version> [--print]}"
MODE="${2:-select}"
APPS_DIR="${XCODE_APPS_DIR:-/Applications}"
PLISTBUDDY=/usr/libexec/PlistBuddy

case "$MAJOR" in
  ''|*[!0-9]*) echo "::error::Xcode major version must be a number, got '$MAJOR'."; exit 1 ;;
esac

candidates=""
for app in "$APPS_DIR"/Xcode_"$MAJOR"*.app "$APPS_DIR"/Xcode.app; do
  [ -d "$app" ] || continue
  real=$(cd "$app" && pwd -P)
  name=$(basename "$real" | tr '[:upper:]' '[:lower:]')
  case "$name" in
    *beta*|*release_candidate*|*_rc*)
      echo "Skipping $app -> $real (pre-release name)"
      continue ;;
  esac
  version=""; build=""
  if [ -f "$real/Contents/version.plist" ]; then
    version=$("$PLISTBUDDY" -c 'Print :CFBundleShortVersionString' "$real/Contents/version.plist" 2>/dev/null || true)
    build=$("$PLISTBUDDY" -c 'Print :ProductBuildVersion' "$real/Contents/version.plist" 2>/dev/null || true)
  fi
  if [ -z "$version" ] || [ -z "$build" ]; then
    echo "Skipping $app -> $real (no version.plist)"
    continue
  fi
  if [ "${version%%.*}" != "$MAJOR" ]; then
    # Xcode.app is only a candidate when it is the wanted major version.
    echo "Skipping $app -> $real (Xcode $version, not $MAJOR.x)"
    continue
  fi
  license=""
  if [ -f "$real/Contents/Resources/LicenseInfo.plist" ]; then
    license=$("$PLISTBUDDY" -c 'Print :licenseType' "$real/Contents/Resources/LicenseInfo.plist" 2>/dev/null || true)
  fi
  if [ "$license" != "GM" ]; then
    case "$(printf '%s' "$license" | tr '[:upper:]' '[:lower:]')" in
      *beta*) echo "Skipping $app -> $real (licenseType $license)" ;;
      *)      echo "::warning::Skipping $real: licenseType is '${license:-missing}', expected GM. If this is a released Xcode, update scripts/ci-select-xcode.sh." ;;
    esac
    continue
  fi
  candidates="${candidates}${version} ${build} ${real}"$'\n'
done

chosen=$(printf '%s' "$candidates" | sort -u | sort -t ' ' -k1,1V | tail -1)
if [ -z "$chosen" ]; then
  echo "::error::No released Xcode $MAJOR.x on this runner. Installed:"
  ls -d "$APPS_DIR"/Xcode*.app 2>/dev/null || true
  exit 1
fi
version=${chosen%% *}
rest=${chosen#* }
build=${rest%% *}
path=${rest#* }
echo "Selected: Xcode $version ($build) at $path"

if [ "$MODE" = "--print" ]; then
  exit 0
fi

sudo xcode-select -s "$path"
xcodebuild -version
sdk=$(xcrun --sdk iphoneos --show-sdk-version)
echo "iOS SDK: $sdk"
if [ "${sdk%%.*}" -lt "$MAJOR" ]; then
  echo "::error::The selected Xcode has the iOS $sdk SDK; iOS $MAJOR or later is required."
  exit 1
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "XCODE_APP=$path"
    echo "XCODE_VERSION=$version"
    echo "XCODE_BUILD=$build"
  } >> "$GITHUB_ENV"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "path=$path"
    echo "version=$version"
    echo "build=$build"
  } >> "$GITHUB_OUTPUT"
fi
