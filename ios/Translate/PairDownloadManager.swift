//
//  PairDownloadManager.swift
//  Translate
//
//  iOS analogue of apertium-android's PairDownloadManager. Where the
//  Android version drives Play Asset Delivery (AssetPackManager), this
//  drives On-Demand Resources (NSBundleResourceRequest).
//
//  Tag convention: each non-bundled pair's tag is `pair_<snake>`, e.g.
//  `pair_spa_cat`. The `apertium-eng-spa` pair is delivered inside the
//  main app install (no tag) so a fresh launch can translate with no
//  network; every other trunk + staging pair downloads on first use.
//

import Foundation
import Combine

final class PairDownloadManager: ObservableObject {
    static let shared = PairDownloadManager()

    /// Every pair the user can actually translate with right now:
    /// either bundled inside the app or already ODR-downloaded.
    @Published private(set) var installed: Set<String> = []

    /// In-flight ODR fetches keyed by pkg. Published so SwiftUI can
    /// drive a progress sheet off `.fractionCompleted` KVO.
    @Published private(set) var inFlight: [String: Progress] = [:]

    /// Active NSBundleResourceRequests kept alive so the pair bundle
    /// stays mounted while we're using it. Keyed by pkg; a new fetch
    /// overwrites the previous request for the same pair (the old one
    /// is released and the system cleans up its resources once no other
    /// request on the same tag is outstanding).
    private var holds: [String: NSBundleResourceRequest] = [:]

    /// KVO tokens for progress observers, tied to the request lifetime.
    private var progressTokens: [String: NSKeyValueObservation] = [:]

    private init() {
        refreshInstalled()
    }

    // MARK: - helpers

    /// Folder name the pair lives under in the app bundle, e.g.
    /// "pair_eng_spa". Matches the resourceTag and the folder ref
    /// in project.yml.
    static func bundleDir(for pair: LanguagePair) -> String {
        "pair_" + pair.pkg
            .replacingOccurrences(of: "apertium-", with: "")
            .replacingOccurrences(of: "-", with: "_")
    }

    /// ODR tag for a pair; identical to bundleDir but kept a distinct
    /// helper to make future renaming cheap.
    static func odrTag(for pair: LanguagePair) -> String {
        bundleDir(for: pair)
    }

    // MARK: - install checks

    /// Re-compute `installed` by asking the bundle which pair dirs are
    /// present on disk. Bundled pairs always count; ODR pairs count if
    /// a previous session cached their tag.
    func refreshInstalled(completion: (() -> Void)? = nil) {
        let group = DispatchGroup()
        var updated: Set<String> = []
        let lock = NSLock()

        for pair in PairCatalog.all {
            let dir = Self.bundleDir(for: pair)
            // A bundled pair has its mode file immediately resolvable
            // without triggering ODR.
            if Bundle.main.url(forResource: pair.forwardMode,
                               withExtension: "mode",
                               subdirectory: dir) != nil {
                lock.lock(); updated.insert(pair.pkg); lock.unlock()
                continue
            }
            // Otherwise ask Apple whether the ODR tag is already cached.
            group.enter()
            let req = NSBundleResourceRequest(tags: [Self.odrTag(for: pair)])
            req.conditionallyBeginAccessingResources { available in
                if available {
                    lock.lock(); updated.insert(pair.pkg); lock.unlock()
                    // Release the hold — we'll re-acquire on explicit use.
                    req.endAccessingResources()
                }
                group.leave()
            }
        }
        group.notify(queue: .main) { [weak self] in
            self?.installed = updated
            completion?()
        }
    }

    func isInstalled(_ pair: LanguagePair) -> Bool {
        installed.contains(pair.pkg)
    }

    // MARK: - fetch

    /// Ensure the pair is available for translate. Bundled pairs return
    /// immediately; ODR pairs fetch (or cache-hit) via
    /// NSBundleResourceRequest. The request is retained in `holds`
    /// until `release(_:)` is called, so subsequent translate() calls
    /// can treat the bundle as live.
    func ensureAvailable(_ pair: LanguagePair,
                         onProgress: @escaping (Double) -> Void,
                         completion: @escaping (Result<Void, Error>) -> Void) {
        // Already known-installed → keep existing hold (if any) and
        // short-circuit.
        if installed.contains(pair.pkg), holds[pair.pkg] != nil {
            completion(.success(()))
            return
        }
        // Bundled-without-hold path (e.g. the baked-in eng-spa pair).
        let dir = Self.bundleDir(for: pair)
        if Bundle.main.url(forResource: pair.forwardMode,
                           withExtension: "mode",
                           subdirectory: dir) != nil {
            installed.insert(pair.pkg)
            completion(.success(()))
            return
        }
        // ODR path — create (or replace) the request and begin.
        let tag = Self.odrTag(for: pair)
        let req = NSBundleResourceRequest(tags: [tag])
        req.loadingPriority = NSBundleResourceRequestLoadingPriorityUrgent
        holds[pair.pkg] = req
        inFlight[pair.pkg] = req.progress

        // Report progress on the main queue.
        progressTokens[pair.pkg] = req.progress.observe(\.fractionCompleted,
                                                       options: [.initial, .new]) { p, _ in
            DispatchQueue.main.async { onProgress(p.fractionCompleted) }
        }

        req.beginAccessingResources { [weak self] error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.progressTokens.removeValue(forKey: pair.pkg)
                self.inFlight.removeValue(forKey: pair.pkg)
                if let error = error {
                    self.holds.removeValue(forKey: pair.pkg)
                    completion(.failure(error))
                } else {
                    self.installed.insert(pair.pkg)
                    completion(.success(()))
                }
            }
        }
    }

    /// Cancel an in-flight fetch for the pair, if any. Safe to call if
    /// there's nothing running.
    func cancel(_ pair: LanguagePair) {
        if let req = holds[pair.pkg], !installed.contains(pair.pkg) {
            req.progress.cancel()
            req.endAccessingResources()
            holds.removeValue(forKey: pair.pkg)
        }
        progressTokens.removeValue(forKey: pair.pkg)
        inFlight.removeValue(forKey: pair.pkg)
    }

    /// Release our hold on the ODR bundle for this pair (bundled pairs
    /// are a no-op). After the last outstanding hold releases, iOS is
    /// free to evict the content to reclaim disk.
    func release(_ pair: LanguagePair) {
        if let req = holds.removeValue(forKey: pair.pkg) {
            req.endAccessingResources()
        }
        progressTokens.removeValue(forKey: pair.pkg)
        inFlight.removeValue(forKey: pair.pkg)
    }
}
