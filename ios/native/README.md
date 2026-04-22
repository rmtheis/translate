# apertium-ios-native

Cross-compile scripts for Apertium's C++ toolchain against the iOS SDK.
Produces static-library slices per platform (device arm64, simulator
arm64, simulator x86_64) and wraps them into `ApertiumCore.xcframework`
for the iOS app target to link.

Parallel to `../android/native/`. The iOS side cannot `fork`/`exec`,
so the app links each Apertium tool as a library — see
`../apertium-ios/README.md` for the architectural rationale.

## Build

Requires:
- Xcode 15+ (we're on 26.4.1; iPhoneOS + iPhoneSimulator SDKs must be
  installed)
- `brew install autoconf automake libtool pkg-config cmake ninja`
- `xcode-select --install` (for the host toolchain)

Sanity-check the toolchain before anything else:

```sh
./build.sh test-toolchain                      # default SLICE=ios-arm64
SLICE=ios-arm64-sim ./build.sh test-toolchain
SLICE=ios-x86_64-sim ./build.sh test-toolchain
```

Full build (blocked until components are implemented step by step per
the plan in `../apertium-ios/README.md`):

```sh
./build.sh xcframework   # all slices + ApertiumCore.xcframework
```

Individual targets match `android/native/build.sh`:
`utfcpp`, `pcre2`, `xml2`, `icu`, `lttoolbox`, `apertium`, `lex-tools`,
`recursive`, `separable`, `anaphora`, `cg3`, `openfst`, `hfst`.

## Slices

| SLICE              | SDK               | Arch   | Typical use                        |
|--------------------|-------------------|--------|------------------------------------|
| `ios-arm64`        | iphoneos          | arm64  | App Store / TestFlight device      |
| `ios-arm64-sim`    | iphonesimulator   | arm64  | Apple Silicon Mac simulator        |
| `ios-x86_64-sim`   | iphonesimulator   | x86_64 | Intel Mac / Rosetta simulator      |

## Output layout

- `build/<slice>/...` — per-component build dirs
- `build/icu-host-build/` + `build/icu-host-install/` — ICU host stage
  (ICU's codegen tools must run on the build host; reused across slices)
- `out/<slice>/` — autotools-style install prefix per slice
- `ApertiumCore.xcframework/` — final packaged output (at repo root)

Static libs only. iOS apps link static archives into the xcframework;
no `.dylib`/`.framework` dance.

## Deviations from `android/native/`

- Toolchain: `xcrun --sdk <sdk> --find clang` instead of the NDK's
  `<triple><api>-clang` wrappers.
- Triples: `aarch64-apple-ios$MIN[-simulator]` or
  `x86_64-apple-ios$MIN-simulator`. The `-ios` suffix (not `-darwin`) is
  necessary on Apple Silicon Macs so autoconf treats arm64 simulator
  builds as cross-compiles rather than native-to-macOS.
- `--enable-static --disable-shared` everywhere (ICU included). No
  `patchelf` or soname fixup — Mach-O static archives, not ELF.
- iOS deployment target: `16.0` by default (override `IOS_MIN`).
- No bionic shims (`shims/glob.h`, `shims/wordexp.h`) — Darwin has both
  natively.
