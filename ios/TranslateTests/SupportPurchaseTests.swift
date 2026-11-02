//
//  SupportPurchaseTests.swift
//  TranslateTests
//
//  Runs SupportPurchase against StoreKit's local test session
//  (Translate.storekit), no App Store or sandbox account involved:
//    xcodebuild test -project Translate.xcodeproj -scheme Translate \
//      -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
//      -parallel-testing-enabled NO
//

import StoreKitTest
import XCTest
@testable import Translate

@MainActor
final class SupportPurchaseTests: XCTestCase {
    private let suite = "SupportPurchaseTests"
    private var session: SKTestSession!
    private var defaults: UserDefaults!

    override func setUp() async throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "Translate", withExtension: "storekit"))
        session = try SKTestSession(contentsOf: url)
        session.disableDialogs = true
        session.failTransactionsEnabled = false  // persists across sessions on the simulator
        session.clearTransactions()
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() async throws {
        session.clearTransactions()
        session = nil  // XCTest keeps finished test cases alive; two live sessions conflict.
        defaults.removePersistentDomain(forName: suite)
    }

    func testNoPriceUntilTheStoreSuppliesOne() async {
        let support = SupportPurchase(defaults: defaults)
        XCTAssertNil(support.formattedPrice)
        await support.loadProduct()
        XCTAssertEqual(support.formattedPrice, "$2.99")
        XCTAssertFalse(support.isSupporter)
    }

    func testPurchaseThanksOnceAndIsRemembered() async {
        let support = SupportPurchase(defaults: defaults)
        await support.purchase()
        XCTAssertTrue(support.isSupporter)
        XCTAssertTrue(support.justPurchased)

        let nextLaunch = SupportPurchase(defaults: defaults)
        XCTAssertTrue(nextLaunch.isSupporter)
        XCTAssertFalse(nextLaunch.justPurchased)
    }

    func testFailedPurchaseChangesNothing() async throws {
        session.failTransactionsEnabled = true
        session.failureError = .unknown
        let support = SupportPurchase(defaults: defaults)
        await support.purchase()
        XCTAssertFalse(support.isSupporter)
        XCTAssertFalse(support.justPurchased)
    }
}
