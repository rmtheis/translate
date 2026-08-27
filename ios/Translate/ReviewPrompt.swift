import StoreKit
import SwiftUI

/// App Store review prompt, gated so it can never nag.
///
/// Two gates must both pass before the sheet is ever requested:
///   - the app has been launched at least `minLaunches` times, and
///   - at least `minDaysSinceFirstLaunch` days have passed since the first launch.
///
/// Both exist to keep the prompt away from people who are still deciding
/// whether they like the app at all — someone who bounces on day one is the
/// most likely to leave a one-star review if asked.
///
/// StoreKit tells us nothing about what the user did with the sheet, and Apple
/// may decline to show it at all against its own 3-per-365-days quota. So every
/// request is treated as a possible dismissal and the app goes quiet for
/// `quietPeriodDays` afterwards.
enum ReviewPrompt {
    private static let minLaunches = 3
    private static let minDaysSinceFirstLaunch = 3

    /// Gap after the sheet has been requested once. Apple caps displays at
    /// 3 per 365 days on its side too, but that is its policy, not ours —
    /// this is the guarantee we actually control.
    private static let quietPeriodDays = 90

    private static let launchCountKey = "reviewPromptLaunchCount"
    private static let firstLaunchTimeKey = "reviewPromptFirstLaunchTime"
    private static let lastRequestedTimeKey = "reviewPromptLastRequestedTime"

    /// Delay before the sheet appears, so it never lands on top of the first
    /// frame while the user is still orienting themselves.
    static let presentationDelay: Duration = .seconds(2)

    /// Records this launch and reports whether every gate now passes.
    /// Call once per launch; the launch counter advances either way.
    static func shouldRequestReview(
        defaults: UserDefaults = .standard,
        now: Date = Date()
    ) -> Bool {
        // Never prompt from a debug build — those launches are ours, and a
        // debug build isn't installed from the App Store, so the sheet would
        // no-op anyway while still burning the quiet period.
        #if DEBUG
        return false
        #else
        let launchCount = recordLaunch(defaults: defaults, now: now)
        guard launchCount >= minLaunches else { return false }

        let firstLaunchTime = defaults.double(forKey: firstLaunchTimeKey)
        guard days(from: firstLaunchTime, to: now) >= minDaysSinceFirstLaunch else {
            return false
        }

        // A zero here means we've never asked — not "asked at the epoch" —
        // so a first-ever qualifying launch isn't made to wait out the whole
        // quiet period.
        let lastRequestedTime = defaults.double(forKey: lastRequestedTimeKey)
        guard lastRequestedTime == 0 || days(from: lastRequestedTime, to: now) >= quietPeriodDays
        else {
            return false
        }

        return true
        #endif
    }

    /// Stamps the quiet period. Called immediately before the sheet is
    /// requested, since StoreKit's request returns no verdict to react to.
    static func markRequested(defaults: UserDefaults = .standard, now: Date = Date()) {
        defaults.set(now.timeIntervalSince1970, forKey: lastRequestedTimeKey)
    }

    /// Bumps the launch counter, seeding the first-launch timestamp on the way
    /// through, and returns the new count.
    @discardableResult
    static func recordLaunch(defaults: UserDefaults = .standard, now: Date = Date()) -> Int {
        if defaults.double(forKey: firstLaunchTimeKey) == 0 {
            defaults.set(now.timeIntervalSince1970, forKey: firstLaunchTimeKey)
        }
        // Saturate rather than letting a long-lived install climb forever.
        let launchCount = min(defaults.integer(forKey: launchCountKey) + 1, minLaunches)
        defaults.set(launchCount, forKey: launchCountKey)
        return launchCount
    }

    private static func days(from epochSeconds: TimeInterval, to now: Date) -> Int {
        Int((now.timeIntervalSince1970 - epochSeconds) / 86_400)
    }
}

private struct ReviewPromptModifier: ViewModifier {
    @Environment(\.requestReview) private var requestReview

    func body(content: Content) -> some View {
        content.task {
            guard ReviewPrompt.shouldRequestReview() else { return }
            try? await Task.sleep(for: ReviewPrompt.presentationDelay)
            // Sleeping means the user may have left; don't ambush them on the
            // way back in with a sheet they didn't see coming.
            guard !Task.isCancelled else { return }
            ReviewPrompt.markRequested()
            requestReview()
        }
    }
}

extension View {
    /// Attach to the root view. Counts the launch and, if the gates pass,
    /// requests the App Store review sheet shortly after first paint.
    func reviewPrompt() -> some View {
        modifier(ReviewPromptModifier())
    }
}
