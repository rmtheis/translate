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

    var body: some View {
        VStack(spacing: 16) {
            Text("Downloading")
                .font(.headline)
            Text(pair.forwardTitle)
                .font(.title2)
                .bold()
                .multilineTextAlignment(.center)
            Text(humanSize(bytes: estimateBytes(pair: pair)))
                .font(.footnote)
                .foregroundStyle(.secondary)

            ProgressView(value: fraction, total: 1.0)
                .progressViewStyle(.linear)
                .frame(maxWidth: 320)

            Text("\(Int(fraction * 100))%")
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()

            if let msg = errorMessage {
                Text(msg)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }

            Button("Cancel", role: .cancel, action: onCancel)
                .buttonStyle(.bordered)
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
