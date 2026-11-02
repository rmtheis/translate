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
    @ObservedObject private var support = SupportPurchase.shared

    /// "Donate" until the App Store's localized price is known, then
    /// "Donate • 2,99 €". No price is ever shown that the App Store did
    /// not supply. See SupportPurchase.
    private var donateLabel: String {
        let donate = String(localized: "Donate")
        guard let price = support.formattedPrice else { return donate }
        return "\(donate) \u{2022} \(price)"
    }

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
                        Text("Apertium Translation Models")
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

                Section {
                    if support.isSupporter {
                        Text("Thank you for supporting this app")
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity)
                    } else {
                        Button {
                            Task { await support.purchase() }
                        } label: {
                            Text(verbatim: donateLabel)
                                .frame(maxWidth: .infinity)
                        }
                    }
                }
            }
            .task { await support.loadProduct() }
            .alert("Thank you", isPresented: $support.justPurchased) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("Your donation supports future development of the app.")
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
    static let supporter = "supporter"
}

#if DEBUG
#Preview { AboutSheet() }
#endif
