//
//  PairDownloadSheet.swift
//  Translate
//
//  Modal sheet shown while a tapped non-bundled pair is downloading
//  via On-Demand Resources. Mirrors apertium-android's download dialog.
//

import SwiftUI

struct PairDownloadSheet: View {
    let pair: LanguagePair
    @Binding var fraction: Double
    @Binding var errorMessage: String?
    var onCancel: () -> Void
    var onRetry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Text(errorMessage == nil ? "Downloading" : "Download failed")
                .font(.headline)
                .foregroundStyle(errorMessage == nil ? Color.primary : Color.red)
            Text(pair.forwardTitle)
                .font(.title2)
                .bold()
                .multilineTextAlignment(.center)
            Text(humanSize(bytes: estimateBytes(pair: pair)))
                .font(.footnote)
                .foregroundStyle(.secondary)

            // Hide progress UI on failure — NSBundleResourceRequest's
            // Progress reports fractionCompleted = 1.0 when the request
            // fails before any bytes transfer (totalUnitCount stays 0),
            // which renders as a misleading "100%" + green bar.
            if let msg = errorMessage {
                Text(msg)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            } else {
                ProgressView(value: fraction, total: 1.0)
                    .progressViewStyle(.linear)
                    .frame(maxWidth: 320)

                Text("\(Int(fraction * 100))%")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            HStack(spacing: 12) {
                if errorMessage != nil {
                    Button("Retry", action: onRetry)
                        .buttonStyle(.borderedProminent)
                }
                Button("Cancel", role: .cancel, action: onCancel)
                    .buttonStyle(.bordered)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .presentationDetents([.height(300)])
    }

    private func humanSize(bytes: Int64) -> String {
        let mb = Double(bytes) / 1024.0 / 1024.0
        if mb >= 1 { return String(format: "%.1f MB", mb) }
        return String(format: "%.0f KB", Double(bytes) / 1024.0)
    }

    private func estimateBytes(pair: LanguagePair) -> Int64 {
        Int64(pair.sizeKb) * 1024
    }
}
