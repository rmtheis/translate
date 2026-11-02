//
//  SupportPurchase.swift
//  Translate
//
//  The one-time "Donate" purchase offered in the About sheet, mirrors
//  Android's SupportPurchase.java. Started when the first screen appears
//  so the App Store's localized price is normally already known by the
//  time the sheet opens. Until the App Store has answered, the row shows
//  the plain "Donate" label: no price is ever shown that the App Store
//  did not supply, in particular never a hardcoded dollar amount.
//
//  The purchase unlocks nothing: the row becomes a thank-you line, that
//  is all. The product is a consumable (a tip, nothing to restore, so no
//  Restore button that App Review would otherwise want), which means the
//  App Store keeps no entitlement to query: the thank-you line lives in
//  UserDefaults, and it stays after a refund (StoreKit's test session
//  delivers no update when a finished consumable is refunded). Offline or
//  without a product the row stays "Donate" and a tap does nothing.
//

import Foundation
import StoreKit
import os.log

@MainActor
final class SupportPurchase: ObservableObject {
    static let shared = SupportPurchase()
    static let productID = "com.qvyshift.translate.support_2026"

    /// The App Store's localized formatted price, nil until the product has loaded.
    @Published private(set) var formattedPrice: String?
    /// True once a completed purchase is known.
    @Published private(set) var isSupporter: Bool
    /// Set right after a purchase completes; the About sheet shows its thank-you alert.
    @Published var justPurchased = false

    private var product: Product?
    private var updatesTask: Task<Void, Never>?
    private let defaults: UserDefaults
    private let log = Logger(subsystem: "com.qvyshift.translate", category: "support")

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        isSupporter = defaults.bool(forKey: AppStorageKey.supporter)
    }

    /// Called when the first screen appears. Listens for transactions that
    /// arrive outside an explicit purchase (Ask to Buy, an interrupted
    /// purchase) and looks the price up.
    func start() async {
        if updatesTask == nil {
            updatesTask = Task { [weak self] in
                for await update in Transaction.updates {
                    await self?.handle(update)
                }
            }
        }
        await loadProduct()
    }

    /// Fetches the product once it is known to be missing (offline at launch).
    func loadProduct() async {
        guard product == nil else { return }
        do {
            let found = try await Product.products(for: [Self.productID]).first
            product = found
            formattedPrice = found?.displayPrice
            log.notice("price \(found?.displayPrice ?? "unavailable", privacy: .public)")
        } catch {
            log.notice("products failed: \(String(describing: error), privacy: .public)")
        }
    }

    /// Opens the App Store's purchase sheet.
    func purchase() async {
        await loadProduct()
        guard let product else { return }
        do {
            switch try await product.purchase() {
            case .success(let verification):
                if await handle(verification) { justPurchased = true }
            case .pending, .userCancelled:
                break  // Ask to Buy: Transaction.updates delivers it if approved.
            @unknown default:
                break
            }
        } catch {
            log.notice("purchase failed: \(String(describing: error), privacy: .public)")
        }
    }

    /// Returns true when the transaction is a completed donation.
    @discardableResult
    private func handle(_ verification: VerificationResult<Transaction>) async -> Bool {
        guard case .verified(let transaction) = verification,
              transaction.productID == Self.productID else { return false }
        let completed = transaction.revocationDate == nil
        if completed {
            isSupporter = true
            defaults.set(true, forKey: AppStorageKey.supporter)
        }
        await transaction.finish()
        return completed
    }
}
