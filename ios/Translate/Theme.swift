//
//  Theme.swift
//  Translate
//
//  Colors from apertium-android's res/values/colors.xml and the translator
//  screen's theme (styles.xml, Theme.App.NoActionBar): pale_brown window and
//  toolbar background, dark_red as colorPrimary/colorAccent. Like the Android
//  app, this one is light-only (UIUserInterfaceStyle = Light in project.yml).
//  The AccentColor asset carries the same red so UIKit-presented chrome
//  (alerts, menus) matches the SwiftUI `.tint`.
//

import SwiftUI

enum Theme {
    /// pale_brown #FFECC0 — Android's windowBackground and toolbar.
    static let background = Color(red: 0xFF / 255, green: 0xEC / 255, blue: 0xC0 / 255)
    /// dark_red #CC0000 — Android's colorPrimary / colorAccent.
    static let accent = Color(red: 0xCC / 255, green: 0, blue: 0)
    /// Unfocused outline of Material's OutlinedBox text fields (on-surface
    /// black at 38%), drawn over the pale brown like on Android.
    static let outline = Color.black.opacity(0.38)
}
