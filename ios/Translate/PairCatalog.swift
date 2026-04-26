//
//  PairCatalog.swift
//  Translate
//
//  Mirror of apertium-android's PairCatalog.java, filtered to TRUNK +
//  STAGING tiers (27 pairs). The full catalog + ODR-gated Nursery/
//  Incubator pairs is future work.
//

import Foundation

enum PairTier: String, CaseIterable, Hashable {
    case trunk = "Trunk"
    case staging = "Staging"

    var displayName: String {
        switch self {
        case .trunk:   return "Active"
        case .staging: return "Staging"
        }
    }
}

struct LanguagePair: Hashable, Identifiable {
    /// e.g. "apertium-eng-spa"
    let pkg: String
    /// Forward direction mode id (e.g. "eng-spa")
    let forwardMode: String
    /// Backward direction mode id, nil if one-way (e.g. "spa-eng")
    let backwardMode: String?
    let sizeKb: Int
    let tier: PairTier

    var id: String { pkg }
    var forwardTitle: String { humanTitle(forwardMode) }
    var backwardTitle: String? { backwardMode.map(humanTitle) }
    var bidirectional: Bool { backwardMode != nil }

    enum Direction { case forward, backward }

    /// Pair data directory. For the bundled `apertium-eng-spa` pair
    /// that's `<App.app>/pair_eng_spa/`. For the 26 ODR-tagged pairs
    /// it's `<App.app>/OnDemandResources/<pack>.assetpack/pair_<snake>/`,
    /// which is why we resolve through `Bundle.main.url(forResource:…)`
    /// rather than concatenating onto `Bundle.main.resourceURL` — the
    /// latter only finds bundled resources, not ODR-delivered ones.
    /// Caller must ensure the resource tag is currently held via
    /// PairDownloadManager.ensureAvailable before this is called.
    func bundleURL() throws -> URL {
        let dirName = PairDownloadManager.bundleDir(for: self)
        if let modeURL = Bundle.main.url(forResource: forwardMode,
                                         withExtension: "mode",
                                         subdirectory: dirName) {
            return modeURL.deletingLastPathComponent()
        }
        throw ApertiumError.missingPair(dirName)
    }

    func modeFileURL(direction: Direction) throws -> URL {
        let dirName = PairDownloadManager.bundleDir(for: self)
        let id = direction == .forward ? forwardMode : (backwardMode ?? forwardMode)
        if let url = Bundle.main.url(forResource: id,
                                     withExtension: "mode",
                                     subdirectory: dirName) {
            return url
        }
        throw ApertiumError.missingPair(dirName)
    }
}

// ISO 639-3 → English names. Generated from apertium-android's
// scripts/_pair_catalog.py ISO_NAMES table.
private let isoNames: [String: String] = [
    "afr": "Afrikaans", "ara": "Arabic", "arg": "Aragonese", "ast": "Asturian",
    "bel": "Belarusian", "bul": "Bulgarian", "cat": "Catalan", "ces": "Czech",
    "crh": "Crimean Tatar", "dan": "Danish", "deu": "German", "ell": "Greek",
    "eng": "English", "epo": "Esperanto", "est": "Estonian", "eus": "Basque",
    "fao": "Faroese", "fin": "Finnish", "fra": "French", "gle": "Irish",
    "glg": "Galician", "haw": "Hawaiian", "hbs": "Serbo-Croatian", "heb": "Hebrew",
    "hin": "Hindi", "hrv": "Croatian", "hun": "Hungarian", "ind": "Indonesian",
    "isl": "Icelandic", "ita": "Italian", "jpn": "Japanese", "kat": "Georgian",
    "kaz": "Kazakh", "kir": "Kyrgyz", "kor": "Korean", "lat": "Latin",
    "lav": "Latvian", "lit": "Lithuanian", "mkd": "Macedonian", "mlt": "Maltese",
    "nld": "Dutch", "nno": "Norwegian Nynorsk", "nob": "Norwegian Bokmål",
    "nor": "Norwegian", "oci": "Occitan", "pol": "Polish", "por": "Portuguese",
    "ron": "Romanian", "rus": "Russian", "sco": "Scots", "slk": "Slovak",
    "slv": "Slovenian", "sme": "Northern Sami", "smn": "Inari Sami",
    "sma": "Southern Sami", "smj": "Lule Sami", "spa": "Spanish",
    "srd": "Sardinian", "swe": "Swedish", "tat": "Tatar", "tur": "Turkish",
    "ukr": "Ukrainian", "uzb": "Uzbek", "vie": "Vietnamese", "zho": "Chinese",
]

private func humanTitle(_ modeId: String) -> String {
    let parts = modeId.split(separator: "-", maxSplits: 1).map(String.init)
    guard parts.count == 2 else { return modeId }
    let src = parts[0].split(separator: "_").first.map(String.init) ?? parts[0]
    let tgt = parts[1].split(separator: "_").first.map(String.init) ?? parts[1]
    return "\(isoNames[src] ?? src) → \(isoNames[tgt] ?? tgt)"
}

enum PairCatalog {
    /// The 27 Trunk + Staging pairs — mirror of Android's
    /// `PairCatalog.ENABLED` (see apertium-android/app/…/PairCatalog.java).
    static let all: [LanguagePair] = [
        // Trunk
        LanguagePair(pkg: "apertium-arg-cat", forwardMode: "arg-cat", backwardMode: "cat-arg", sizeKb: 7_695, tier: .trunk),
        LanguagePair(pkg: "apertium-bel-rus", forwardMode: "bel-rus", backwardMode: "rus-bel", sizeKb: 5_690, tier: .trunk),
        LanguagePair(pkg: "apertium-cat-ita", forwardMode: "cat-ita", backwardMode: "ita-cat", sizeKb: 11_772, tier: .trunk),
        LanguagePair(pkg: "apertium-cat-srd", forwardMode: "cat-srd", backwardMode: nil,       sizeKb: 9_516, tier: .trunk),
        LanguagePair(pkg: "apertium-dan-nor", forwardMode: "dan-nob", backwardMode: "nob-dan", sizeKb: 14_865, tier: .trunk),
        LanguagePair(pkg: "apertium-eng-cat", forwardMode: "eng-cat", backwardMode: "cat-eng", sizeKb: 15_851, tier: .trunk),
        LanguagePair(pkg: "apertium-eng-spa", forwardMode: "eng-spa", backwardMode: "spa-eng", sizeKb: 5_466, tier: .trunk),
        LanguagePair(pkg: "apertium-fra-cat", forwardMode: "fra-cat", backwardMode: "cat-fra", sizeKb: 17_268, tier: .trunk),
        LanguagePair(pkg: "apertium-hbs-eng", forwardMode: "hbs-eng", backwardMode: "eng-hbs", sizeKb: 5_246, tier: .trunk),
        LanguagePair(pkg: "apertium-hbs-mkd", forwardMode: "hbs-mkd", backwardMode: "mkd-hbs_SR", sizeKb: 2_889, tier: .trunk),
        LanguagePair(pkg: "apertium-mkd-eng", forwardMode: "mkd-eng", backwardMode: nil,       sizeKb: 1_911, tier: .trunk),
        LanguagePair(pkg: "apertium-nno-nob", forwardMode: "nno-nob", backwardMode: "nob-nno", sizeKb: 34_104, tier: .trunk),
        LanguagePair(pkg: "apertium-oci-cat", forwardMode: "oci-cat", backwardMode: "cat-oci", sizeKb: 12_958, tier: .trunk),
        LanguagePair(pkg: "apertium-oci-fra", forwardMode: "oci-fra", backwardMode: "fra-oci", sizeKb: 34_120, tier: .trunk),
        LanguagePair(pkg: "apertium-por-cat", forwardMode: "por-cat", backwardMode: "cat-por", sizeKb: 14_613, tier: .trunk),
        LanguagePair(pkg: "apertium-ron-cat", forwardMode: "ron-cat", backwardMode: "cat-ron", sizeKb: 9_510, tier: .trunk),
        LanguagePair(pkg: "apertium-rus-ukr", forwardMode: "rus-ukr", backwardMode: "ukr-rus", sizeKb: 5_092, tier: .trunk),
        LanguagePair(pkg: "apertium-sme-nob", forwardMode: "sme-nob", backwardMode: nil,       sizeKb: 90_300, tier: .trunk),
        LanguagePair(pkg: "apertium-spa-arg", forwardMode: "spa-arg", backwardMode: "arg-spa", sizeKb: 5_366, tier: .trunk),
        LanguagePair(pkg: "apertium-spa-ast", forwardMode: "spa-ast", backwardMode: nil,       sizeKb: 5_582, tier: .trunk),
        LanguagePair(pkg: "apertium-spa-cat", forwardMode: "spa-cat", backwardMode: "cat-spa", sizeKb: 19_470, tier: .trunk),
        LanguagePair(pkg: "apertium-spa-glg", forwardMode: "spa-glg", backwardMode: "glg-spa", sizeKb: 12_142, tier: .trunk),
        LanguagePair(pkg: "apertium-spa-ita", forwardMode: "spa-ita", backwardMode: "ita-spa", sizeKb: 5_488, tier: .trunk),
        LanguagePair(pkg: "apertium-srd-ita", forwardMode: "srd-ita", backwardMode: "ita-srd", sizeKb: 8_029, tier: .trunk),
        LanguagePair(pkg: "apertium-swe-dan", forwardMode: "swe-dan", backwardMode: "dan-swe", sizeKb: 9_581, tier: .trunk),
        LanguagePair(pkg: "apertium-swe-nor", forwardMode: "swe-nob", backwardMode: "nob-swe", sizeKb: 21_335, tier: .trunk),
        // Staging
        LanguagePair(pkg: "apertium-cat-glg", forwardMode: "cat-glg", backwardMode: nil,       sizeKb: 8_317, tier: .staging),
    ]

    /// Pairs grouped by tier, each group sorted by forward title. Used
    /// by the picker to render section headers like the Android adapter.
    static var byTier: [(tier: PairTier, pairs: [LanguagePair])] {
        PairTier.allCases.compactMap { tier in
            let items = all.filter { $0.tier == tier }
                .sorted { $0.forwardTitle < $1.forwardTitle }
            return items.isEmpty ? nil : (tier, items)
        }
    }

    static func find(pkg: String) -> LanguagePair? {
        all.first { $0.pkg == pkg }
    }
}
