//
//  TranslatorView.swift
//  Translate
//
//  Port of apertium-android's TranslatorActivity layout:
//    - Pair picker (tier-grouped)
//    - Source field (with copy + paste icons overlaid bottom-right)
//    - Translate button (full row width) + swap button to its right
//    - Target field (with copy + paste icons overlaid bottom-right)
//

import SwiftUI

struct TranslatorView: View {
    @AppStorage(AppStorageKey.lastPairPkg)   private var selectedPkg: String = "apertium-eng-spa"
    @AppStorage(AppStorageKey.lastDirection) private var directionRaw: String = "forward"
    @AppStorage(AppStorageKey.displayMarks)  private var displayMarks: Bool = true

    @StateObject private var downloads = PairDownloadManager.shared

    @State private var input = ""
    @State private var output = ""
    @State private var errorMessage: String?
    @State private var translating = false
    @State private var showAbout = false

    // ODR download state; non-nil while a fetch is in progress for a
    // picker-selected pair.
    @State private var downloadingPair: LanguagePair?
    @State private var downloadFraction: Double = 0
    @State private var downloadError: String?

    private var selectedPair: LanguagePair {
        PairCatalog.find(pkg: selectedPkg) ?? PairCatalog.all[0]
    }
    private var direction: LanguagePair.Direction {
        get { directionRaw == "backward" ? .backward : .forward }
    }

    /// Whether we were launched into App-Store screenshot mode. The
    /// script in scripts/screenshots.sh passes launch args that set the
    /// pair, direction, and input; the view auto-runs translate on appear.
    private var screenshotLaunchInput: String? {
        let args = ProcessInfo.processInfo.arguments
        if let idx = args.firstIndex(of: "-screenshot_pair"), idx + 1 < args.count {
            selectedPkgOverride = args[idx + 1]
        }
        if let idx = args.firstIndex(of: "-screenshot_direction"), idx + 1 < args.count {
            directionOverride = args[idx + 1]
        }
        if let idx = args.firstIndex(of: "-screenshot_input"), idx + 1 < args.count {
            return args[idx + 1]
        }
        return nil
    }

    // Read-only because ProcessInfo is read once per launch.
    @State private var selectedPkgOverride: String? = nil
    @State private var directionOverride: String? = nil

    // Tracks whether the source TextEditor has keyboard focus so we
    // can dismiss the keyboard from the toolbar "Done" button.
    @FocusState private var inputFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(alignment: .center, spacing: 8) {
                pairPicker
                textField(isSource: true,
                          label: sideTitle(source: true),
                          text: $input,
                          readOnly: false)
                actionRow
                textField(isSource: false,
                          label: sideTitle(source: false),
                          text: .constant(output),
                          readOnly: true)
            }
            .padding(.horizontal, 12)
            .padding(.top, 4)
            .navigationTitle("Apertium Translate Models")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAbout = true } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
                // "Done" button above the keyboard so users can dismiss
                // it — TextEditor's Return key inserts a newline and
                // doesn't offer a built-in submit path.
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { inputFocused = false }
                }
            }
            .sheet(isPresented: $showAbout) {
                AboutSheet()
                    .presentationDetents([.medium, .large])
            }
            .sheet(item: $downloadingPair) { pair in
                PairDownloadSheet(pair: pair,
                                  fraction: $downloadFraction,
                                  errorMessage: $downloadError,
                                  onCancel: {
                    downloads.cancel(pair)
                    downloadingPair = nil
                })
            }
            .onAppear { applyScreenshotLaunchArgs() }
            .alert("Translation error",
                   isPresented: Binding(get: { errorMessage != nil },
                                        set: { if !$0 { errorMessage = nil } })) {
                Button("OK", role: .cancel) { errorMessage = nil }
            } message: { Text(errorMessage ?? "") }
        }
    }

    // MARK: - subviews

    private var pairPicker: some View {
        Menu {
            ForEach(PairCatalog.byTier, id: \.tier) { group in
                Section(group.tier.displayName) {
                    ForEach(group.pairs) { pair in
                        pairMenuItem(pair)
                    }
                }
            }
        } label: {
            HStack {
                Text(pairTitle(selectedPair, direction: direction))
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "chevron.down")
                    .foregroundStyle(.secondary)
                    .font(.footnote)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.secondary.opacity(0.4), lineWidth: 1)
            )
        }
    }

    private func pairMenuItem(_ pair: LanguagePair) -> some View {
        Button {
            handlePairTapped(pair)
        } label: {
            HStack {
                Text(pair.forwardTitle)
                Spacer()
                // Trailing marker: checkmark for the currently-selected
                // pair; download-arrow for pairs not yet installed via
                // ODR; nothing otherwise (installed-but-not-selected).
                if pair.pkg == selectedPair.pkg {
                    Image(systemName: "checkmark")
                } else if !downloads.isInstalled(pair) {
                    Image(systemName: "arrow.down.circle")
                }
            }
        }
    }

    private func textField(isSource: Bool,
                           label: String,
                           text: Binding<String>,
                           readOnly: Bool) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 4)
            ZStack(alignment: .bottomTrailing) {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(Color.secondary.opacity(0.4), lineWidth: 1)
                sourceAwareEditor(text: text, isSource: isSource)
                    .disabled(readOnly)
                    .scrollContentBackground(.hidden)
                    .padding(.horizontal, 10)
                    .padding(.top, 8)
                    .padding(.bottom, 44)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.sentences)
                HStack(spacing: 8) {
                    iconButton("doc.on.doc") {
                        UIPasteboard.general.string = text.wrappedValue
                    }
                    .disabled(text.wrappedValue.isEmpty)
                    // Paste button only on the source field — the target
                    // is read-only and pasting into it makes no sense.
                    if !readOnly {
                        iconButton("doc.on.clipboard") {
                            if let s = UIPasteboard.general.string { text.wrappedValue = s }
                        }
                    }
                }
                .padding(.trailing, 14)
                .padding(.bottom, 10)
            }
            .frame(maxWidth: .infinity)
        }
    }

    /// TextEditor that attaches `$inputFocused` only for the source
    /// (editable) field. The target field skips focus tracking so its
    /// read-only state doesn't fight with keyboard-dismissal logic.
    @ViewBuilder
    private func sourceAwareEditor(text: Binding<String>, isSource: Bool) -> some View {
        if isSource {
            TextEditor(text: text).focused($inputFocused)
        } else {
            TextEditor(text: text)
        }
    }

    private func iconButton(_ systemName: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 18, weight: .regular))
                .foregroundStyle(.secondary)
                .frame(width: 36, height: 36)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var actionRow: some View {
        HStack(spacing: 8) {
            Button(action: translate) {
                if translating {
                    ProgressView().frame(maxWidth: .infinity)
                } else {
                    Text("TRANSLATE").frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(input.trimmingCharacters(in: .whitespaces).isEmpty || translating)

            Button(action: swapDirection) {
                Image(systemName: "arrow.up.arrow.down")
                    .font(.system(size: 22, weight: .regular))
                    .frame(width: 48, height: 48)
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - labels

    private func sideTitle(source: Bool) -> String {
        let title = pairTitle(selectedPair, direction: direction)
        let parts = title.components(separatedBy: " → ")
        guard parts.count == 2 else { return source ? "Source" : "Target" }
        return source ? parts[0] : parts[1]
    }

    private func pairTitle(_ pair: LanguagePair,
                           direction: LanguagePair.Direction) -> String {
        switch direction {
        case .forward:  return pair.forwardTitle
        case .backward: return pair.backwardTitle ?? pair.forwardTitle
        }
    }

    // MARK: - actions

    /// Picker-tap handler: if the pair is installed, just switch to it;
    /// otherwise kick off an ODR fetch and show the download sheet. The
    /// previous pair stays selected until the download succeeds.
    private func handlePairTapped(_ pair: LanguagePair) {
        if downloads.isInstalled(pair) {
            selectedPkg = pair.pkg
            directionRaw = "forward"
            output = ""
            return
        }
        downloadFraction = 0
        downloadError = nil
        downloadingPair = pair
        downloads.ensureAvailable(pair, onProgress: { fraction in
            downloadFraction = fraction
        }, completion: { result in
            switch result {
            case .success:
                downloadingPair = nil
                selectedPkg = pair.pkg
                directionRaw = "forward"
                output = ""
            case .failure(let err):
                downloadError = "\(err.localizedDescription)"
            }
        })
    }

    private func swapDirection() {
        guard selectedPair.bidirectional else {
            errorMessage = "This pair is one-way only."
            return
        }
        directionRaw = (direction == .forward) ? "backward" : "forward"
        (input, output) = (output, input)
    }

    /// In screenshot mode: pre-populate the pair, direction, and input,
    /// then run translate automatically so the UI is ready to capture.
    private func applyScreenshotLaunchArgs() {
        guard let input = screenshotLaunchInput else { return }
        if let pkg = selectedPkgOverride { selectedPkg = pkg }
        if let dir = directionOverride  { directionRaw = dir }
        self.input = input
        // Tiny delay so the picker label updates before translate runs;
        // otherwise the screenshot could miss the rebind.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.translate() }
    }

    private func translate() {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        translating = true

        let pair = selectedPair
        downloads.ensureAvailable(pair, onProgress: { _ in }, completion: { result in
            switch result {
            case .failure(let err):
                translating = false
                errorMessage = "\(err)"
                return
            case .success:
                break
            }
            do {
                let modeFile = try pair.modeFileURL(direction: direction)
                let pairDir  = try pair.bundleURL()
                ApertiumEngine.shared.translateAsync(input: trimmed,
                                                     modeFile: modeFile,
                                                     pairBaseDir: pairDir,
                                                     displayMarks: displayMarks) { result in
                    translating = false
                    switch result {
                    case .success(let text): output = text
                    case .failure(let err):  errorMessage = "\(err)"
                    }
                }
            } catch {
                translating = false
                errorMessage = "\(error)"
            }
        })
    }
}

#if DEBUG
#Preview { TranslatorView() }
#endif
