//
//  AboutSheet.swift
//  Translate
//
//  Combined About + Settings sheet — mirrors apertium-android's
//  dialog_about_settings.xml. Shows app identity and a single setting:
//  whether to display `*` markers on words Apertium couldn't translate.
//

import SwiftUI

struct AboutSheet: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage(AppStorageKey.displayMarks) private var displayMarks: Bool = true

    /// Read the marketing version from Info.plist so we don't hard-code
    /// it twice. Shown as "v1.0.0" to match the Android About dialog.
    private var versionLabel: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        return "v" + (v ?? "?")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 6) {
                        Text("Apertium Translate Models")
                            .font(.title.bold())
                            .multilineTextAlignment(.center)
                        Text(versionLabel)
                            .font(.body)
                        Text("\u{00A9}2026 Qvyshift LLC")
                            .font(.body)
                            .foregroundStyle(.secondary)
                        Link(destination: URL(string: "https://github.com/rmtheis/translate")!) {
                            Text("github.com/rmtheis/translate")
                                .font(.body)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                }

                Section {
                    Toggle(isOn: $displayMarks) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Mark unknown words")
                            Text("Mark unknown words with a *")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

enum AppStorageKey {
    static let displayMarks = "displayMark"    // matches Android's App.PREF_displayMark
    static let lastPairPkg  = "lastPairPkg"
    static let lastDirection = "lastDirection"
}

#if DEBUG
#Preview { AboutSheet() }
#endif
