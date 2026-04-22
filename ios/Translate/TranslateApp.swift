//
//  TranslateApp.swift
//  Translate
//

import SwiftUI
import os.log

@main
struct TranslateApp: App {
    init() {
        // Smoke test: translate at launch so we can verify the Swift
        // bridge end-to-end from the console. Remove once a UI test
        // runs the same assertion.
        DispatchQueue.global(qos: .userInitiated).async {
            let log = Logger(subsystem: "com.qvyshift.translate", category: "boot")
            // Pin to eng-spa for the boot-time smoke; the catalog's
            // all[0] changes as pairs are added.
            guard let pair = PairCatalog.find(pkg: "apertium-eng-spa") else {
                log.error("smoke: eng-spa missing from catalog")
                return
            }
            do {
                let modeFile = try pair.modeFileURL(direction: .backward)
                let pairDir  = try pair.bundleURL()
                let out = try ApertiumEngine.shared.translate(
                    input: "Hola",
                    modeFile: modeFile,
                    pairBaseDir: pairDir)
                log.notice("smoke: spa→eng 'Hola' → '\(out, privacy: .public)'")
            } catch {
                log.error("smoke: failed \(String(describing: error), privacy: .public)")
            }
        }
    }

    var body: some Scene {
        WindowGroup {
            TranslatorView()
        }
    }
}
