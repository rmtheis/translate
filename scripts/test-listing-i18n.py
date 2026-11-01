#!/usr/bin/env python3
"""Offline checks of the per-locale store texts the release workflows post.

    python3 scripts/test-listing-i18n.py

No network, no credentials. Loads the real listings (ios/appstore/listings/,
android/play/listings/), the real pair inventory (.ci/prior-pair-inventory-*.json)
and the composing functions of asc_release_notes.py,
update-appstore-description.py and update-store-description.py, and checks that
  * no non-English locale ever receives the English release notes, the English
    pair-list anchor or the English block;
  * the per-release splice of each locale's pair list gives exactly what
    _listing_i18n composes for the upload scripts, so CI and a manual upload agree;
  * the en-US summary carries the real size (the "0 MB" bug).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import _listing_i18n as i18n  # noqa: E402
from _pair_catalog import load as load_catalog  # noqa: E402


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


asc_notes = load_script("asc_release_notes")
play_notes = load_script("play_release_notes")
asc_desc = load_script("update-appstore-description")
play_desc = load_script("update-store-description")

ENGLISH_STOCK = "Behind-the-scenes changes to keep things running smoothly."
ENGLISH_DIFF = "New: Catalan ↔ Sardinian\nUpdated: Catalan ↔ Italian (1.1.0 → 1.1.1)"
NAMES = i18n.load_names()
CATALOG = load_catalog()
IOS_LISTINGS = i18n.load_listings(REPO / "ios/appstore/listings", "locale")
PLAY_LISTINGS = i18n.load_listings(REPO / "android/play/listings", "language")
IOS_INVENTORY = json.loads((REPO / ".ci/prior-pair-inventory-ios.json").read_text())
PLAY_INVENTORY = json.loads((REPO / ".ci/prior-pair-inventory-android.json").read_text())


def older(inventory: list[dict]) -> list[dict]:
    """A plausible previous release: two pairs fewer, one pair smaller."""
    old = copy.deepcopy(inventory[:-2])
    old[0]["bytes"] -= 500_000
    return old


class ReleaseNotes(unittest.TestCase):
    by_locale = {l["locale"]: l for l in IOS_LISTINGS}

    def test_every_drafted_locale_has_a_stock_line(self):
        for listing in IOS_LISTINGS:
            self.assertTrue(listing.get("whatsNew", "").strip(), listing["locale"])

    def test_english_locales_get_the_english_notes(self):
        for english in (ENGLISH_STOCK, ENGLISH_DIFF):
            for locale in ("en-US", "en-GB", "en-AU", "en-CA"):
                self.assertEqual(asc_notes.text_for_locale(locale, english, self.by_locale), english)

    def test_other_locales_get_their_own_stock_line_never_english(self):
        for english in (ENGLISH_STOCK, ENGLISH_DIFF):
            known_english = asc_notes.english_texts(english, IOS_LISTINGS)
            self.assertIn(ENGLISH_STOCK, known_english)
            for listing in IOS_LISTINGS:
                locale = listing["locale"]
                if i18n.english_locale(locale):
                    continue
                text = asc_notes.text_for_locale(locale, english, self.by_locale)
                self.assertEqual(text, listing["whatsNew"].strip(), locale)
                self.assertNotIn(text, known_english, locale)
                self.assertNotIn("Behind-the-scenes", text, locale)
                asc_notes.check_text(locale, text, known_english)  # must not exit

    def test_undrafted_non_english_locale_is_skipped(self):
        self.assertIsNone(asc_notes.text_for_locale("de-DE", ENGLISH_DIFF, self.by_locale))
        without = dict(self.by_locale)
        without["fr-FR"] = {**self.by_locale["fr-FR"], "whatsNew": ""}
        self.assertIsNone(asc_notes.text_for_locale("fr-FR", ENGLISH_DIFF, without))

    def test_guard_refuses_english_text_for_a_non_english_locale(self):
        known_english = asc_notes.english_texts(ENGLISH_DIFF, IOS_LISTINGS)
        with self.assertRaises(SystemExit):
            asc_notes.check_text("fr-FR", ENGLISH_STOCK, known_english)
        with self.assertRaises(SystemExit):
            asc_notes.check_text("ca", ENGLISH_DIFF, known_english)
        asc_notes.check_text("en-GB", ENGLISH_DIFF, known_english)  # English may have it

    def test_plan_covers_en_us_and_every_drafted_locale(self):
        plan = asc_notes.plan_texts(ENGLISH_DIFF, IOS_LISTINGS)
        self.assertEqual(set(plan), {"en-US"} | set(self.by_locale))
        self.assertEqual(plan["en-US"], ENGLISH_DIFF)
        self.assertEqual(plan["uk"], self.by_locale["uk"]["whatsNew"])


class PlayReleaseNotes(unittest.TestCase):
    """scripts/play_release_notes.py: the whatsnew-<language> files of a Play release."""
    by_language = {l["language"]: l for l in PLAY_LISTINGS}

    def test_every_listing_language_has_a_stock_line(self):
        for listing in PLAY_LISTINGS:
            self.assertTrue(listing.get("whatsNew", "").strip(), listing["language"])

    def test_english_languages_get_the_english_notes(self):
        for english in (ENGLISH_STOCK, ENGLISH_DIFF):
            for language in ("en-US", "en-GB", "en-AU", "en-CA"):
                self.assertEqual(play_notes.text_for_language(language, english, self.by_language), english)

    def test_other_languages_get_their_own_stock_line_never_english(self):
        for english in (ENGLISH_STOCK, ENGLISH_DIFF):
            known_english = play_notes.english_texts(english, PLAY_LISTINGS)
            self.assertIn(ENGLISH_STOCK, known_english)
            for listing in PLAY_LISTINGS:
                language = listing["language"]
                if i18n.english_locale(language):
                    continue
                text = play_notes.text_for_language(language, english, self.by_language)
                self.assertEqual(text, listing["whatsNew"].strip(), language)
                self.assertNotIn(text, known_english, language)
                self.assertNotIn("Behind-the-scenes", text, language)
                play_notes.check_text(language, text, known_english)  # must not exit

    def test_guard_refuses_english_text_for_a_non_english_language(self):
        known_english = play_notes.english_texts(ENGLISH_DIFF, PLAY_LISTINGS)
        with self.assertRaises(SystemExit):
            play_notes.check_text("fr-FR", ENGLISH_STOCK, known_english)
        with self.assertRaises(SystemExit):
            play_notes.check_text("uk", ENGLISH_DIFF, known_english)
        play_notes.check_text("en-GB", ENGLISH_DIFF, known_english)  # English may have it

    def test_files_cover_en_us_and_every_listing_language(self):
        for english in (ENGLISH_STOCK, ENGLISH_DIFF):
            with tempfile.TemporaryDirectory() as tmp:
                out = pathlib.Path(tmp)
                play_notes.write_files(play_notes.plan_texts(english, PLAY_LISTINGS), out)
                self.assertEqual({p.name for p in out.iterdir()},
                                 {"whatsnew-en-US"} | {f"whatsnew-{l}" for l in self.by_language})
                self.assertEqual((out / "whatsnew-en-US").read_text(), english + "\n")
                self.assertEqual((out / "whatsnew-en-GB").read_text(), english + "\n")
                self.assertEqual((out / "whatsnew-uk").read_text().strip(),
                                 self.by_language["uk"]["whatsNew"].strip())
                for path in out.iterdir():
                    if not i18n.english_locale(path.name.removeprefix("whatsnew-")):
                        self.assertNotIn("Behind-the-scenes", path.read_text(), path.name)
                        self.assertNotIn("Updated:", path.read_text(), path.name)

    def test_listing_without_stock_line_is_left_out_with_a_warning(self):
        without = [dict(l, whatsNew="") if l["language"] == "fr-FR" else l for l in PLAY_LISTINGS]
        plan = play_notes.plan_texts(ENGLISH_DIFF, without)
        self.assertNotIn("fr-FR", plan)
        self.assertEqual(plan["fr-CA"], self.by_language["fr-CA"]["whatsNew"].strip())


class AppStoreDescription(unittest.TestCase):
    by_locale = {l["locale"]: l for l in IOS_LISTINGS}

    def test_en_us_block_has_the_real_size_and_count(self):
        block = asc_desc.english_block(IOS_INVENTORY, CATALOG)
        mb = i18n.inventory_mb(IOS_INVENTORY)
        self.assertGreater(mb, 0)
        self.assertIn(f"\n{len(IOS_INVENTORY)} pairs, {mb} MB on demand\n", block)
        self.assertNotIn(" 0 MB", block)
        self.assertEqual(block.count("\n• "), len(IOS_INVENTORY))

    def test_inventory_mb_reads_bytes_and_falls_back_to_size_kb(self):
        self.assertEqual(i18n.inventory_mb([{"bytes": 3 * 1024 * 1024}]), 3)
        self.assertEqual(i18n.inventory_mb([{"sizeKb": 2048}]), 2)

    def test_en_us_splice_keeps_the_preamble_and_replaces_the_list(self):
        anchor, block = asc_desc.anchor_and_block("en-US", self.by_locale, IOS_INVENTORY, NAMES, CATALOG)
        self.assertEqual(anchor, "Language pairs:\n")
        current = "Preamble.\n\nLanguage pairs:\n\n27 pairs, 0 MB on demand\n\n• Old ↔ List"
        new = asc_desc.splice(current, anchor, block)
        self.assertTrue(new.startswith("Preamble.\n\nLanguage pairs:\n"))
        self.assertEqual(new, "Preamble.\n\nLanguage pairs:\n" + block)
        self.assertNotIn("0 MB", new)
        self.assertIsNone(asc_desc.splice("No anchor here", anchor, block))

    def test_drafted_locales_splice_to_exactly_the_composed_description(self):
        old = older(IOS_INVENTORY)
        for listing in IOS_LISTINGS:
            locale = listing["locale"]
            current = i18n.appstore_description(listing, old, NAMES, CATALOG)
            anchor, block = asc_desc.anchor_and_block(locale, self.by_locale, IOS_INVENTORY, NAMES, CATALOG)
            self.assertEqual(anchor, listing["pairsHeading"] + "\n", locale)
            new = asc_desc.splice(current, anchor, block)
            self.assertEqual(new, i18n.appstore_description(listing, IOS_INVENTORY, NAMES, CATALOG), locale)
            self.assertEqual(new.count("\n• "), len(IOS_INVENTORY), locale)
            if not i18n.english_locale(locale):
                self.assertNotIn("Language pairs:", new, locale)
                self.assertNotIn(" pairs, ", new, locale)
                # "Catalan" is French too; "English"/"Spanish" are English only.
                self.assertNotIn("• English ", new, locale)
                self.assertNotIn("Spanish", new, locale)

    def test_undrafted_non_english_locale_gets_nothing(self):
        self.assertIsNone(asc_desc.anchor_and_block("de-DE", self.by_locale, IOS_INVENTORY, NAMES, CATALOG))
        # An English variant without a JSON still gets the English block.
        anchor, _ = asc_desc.anchor_and_block("en-IN", self.by_locale, IOS_INVENTORY, NAMES, CATALOG)
        self.assertEqual(anchor, "Language pairs:\n")

    def test_pair_block_matches_the_listing_locale_names(self):
        for listing in IOS_LISTINGS:
            block = i18n.appstore_pair_block(listing, IOS_INVENTORY, NAMES, CATALOG)
            names = NAMES[listing["locale"]]
            spanish = names["spa"][0].upper() + names["spa"][1:]
            self.assertIn(f"• {spanish} ", block, listing["locale"])


class PlayDescription(unittest.TestCase):
    by_lang = {l["language"]: l for l in PLAY_LISTINGS}
    english_block = ("Included language pairs (27 pairs, 169 MB offline):\n\n"
                     "• Aragonese ↔ Catalan\n• Catalan ↔ Italian")

    def test_default_language_gets_the_store_listing_block(self):
        block = play_desc.block_for("en-US", "en-US", self.english_block, self.by_lang,
                                    PLAY_INVENTORY, NAMES, CATALOG)
        self.assertEqual(block, self.english_block)

    def test_drafted_languages_splice_to_exactly_the_composed_description(self):
        old = older(PLAY_INVENTORY)
        for listing in PLAY_LISTINGS:
            lang = listing["language"]
            current = i18n.play_full_description(listing, old, NAMES, CATALOG)
            block = play_desc.block_for(lang, "en-US", self.english_block, self.by_lang,
                                        PLAY_INVENTORY, NAMES, CATALOG)
            self.assertNotEqual(block, self.english_block, lang)
            new = play_desc.splice(current, block)
            self.assertEqual(new, i18n.play_full_description(listing, PLAY_INVENTORY, NAMES, CATALOG), lang)
            self.assertEqual(new.count(i18n.PLAY_START), 1, lang)
            self.assertEqual(new.count(i18n.PLAY_END), 1, lang)
            self.assertEqual(new.count("\n• "), len(PLAY_INVENTORY), lang)
            if not i18n.english_locale(lang):
                self.assertNotIn("Included language pairs", new, lang)
                self.assertNotIn("• English ", new, lang)
                self.assertNotIn("Spanish", new, lang)

    def test_undrafted_language_gets_nothing(self):
        self.assertIsNone(play_desc.block_for("de-DE", "en-US", self.english_block, self.by_lang,
                                              PLAY_INVENTORY, NAMES, CATALOG))

    def test_missing_markers_append_for_default_language_only(self):
        self.assertIsNone(play_desc.splice("Preamble without markers.", "BLOCK"))
        appended = play_desc.splice("Preamble without markers.", "BLOCK", append=True)
        self.assertEqual(appended, f"Preamble without markers.\n\n{i18n.PLAY_START}\nBLOCK\n{i18n.PLAY_END}")

    def test_splice_replaces_only_between_the_markers(self):
        current = f"Keep me.\n\n{i18n.PLAY_START}\nold\n{i18n.PLAY_END}\n\nAnd me."
        self.assertEqual(play_desc.splice(current, "new"),
                         f"Keep me.\n\n{i18n.PLAY_START}\nnew\n{i18n.PLAY_END}\n\nAnd me.")


class Collation(unittest.TestCase):
    """sorted_for() must give the same order on the Mac and on the ubuntu runner."""

    def test_ukrainian_i_sorts_between_d_and_k_not_before_a(self):
        labels = ["Іспанська ↔ Каталонська", "Каталонська ↔ Італійська",
                  "Англійська ↔ Іспанська", "Данська ↔ Норвезька"]
        self.assertEqual(i18n.sorted_for("uk", labels),
                         ["Англійська ↔ Іспанська", "Данська ↔ Норвезька",
                          "Іспанська ↔ Каталонська", "Каталонська ↔ Італійська"])

    def test_croatian_s_caron_follows_s(self):
        labels = ["Švedski ↔ Danski", "Španjolski ↔ Aragonski", "Srpsko-hrvatski ↔ Engleski",
                  "Sardski ↔ Talijanski", "Portugalski ↔ Katalonski"]
        self.assertEqual(i18n.sorted_for("hr", labels),
                         ["Portugalski ↔ Katalonski", "Sardski ↔ Talijanski",
                          "Srpsko-hrvatski ↔ Engleski", "Španjolski ↔ Aragonski", "Švedski ↔ Danski"])

    def test_arrows_are_ignored_and_accents_do_not_split_a_letter(self):
        self.assertEqual(i18n.sorted_for("fr-FR", ["Catalan → Sarde", "Catalan ↔ Italien"]),
                         ["Catalan ↔ Italien", "Catalan → Sarde"])
        self.assertEqual(i18n.sorted_for("ca", ["Èuscar ↔ X", "Espanyol ↔ Y", "Francès ↔ Z"]),
                         ["Espanyol ↔ Y", "Èuscar ↔ X", "Francès ↔ Z"])

    def test_nordic_letters_sort_after_z(self):
        self.assertEqual(i18n.sorted_for("da-DK", ["Åland ↔ X", "Ærø ↔ Y", "Zulu ↔ Z", "Dansk ↔ W"]),
                         ["Dansk ↔ W", "Zulu ↔ Z", "Ærø ↔ Y", "Åland ↔ X"])
        self.assertEqual(i18n.sorted_for("sv-SE", ["Ö ↔ a", "Ä ↔ a", "Å ↔ a", "Z ↔ a"]),
                         ["Z ↔ a", "Å ↔ a", "Ä ↔ a", "Ö ↔ a"])

    def test_english_keeps_the_live_en_us_order(self):
        # The live en-US list is sorted() on the labels: "→" (U+2192) before "↔" (U+2194).
        labels = ["Catalan ↔ Italian", "Catalan → Sardinian", "Aragonese ↔ Catalan"]
        self.assertEqual(i18n.sorted_for("en-GB", labels), sorted(labels))

    def test_order_does_not_depend_on_the_process_locale(self):
        import locale
        labels = [l[2:] for l in i18n.pair_lines(IOS_INVENTORY, "uk", NAMES, CATALOG)]
        before = i18n.sorted_for("uk", labels)
        old = locale.setlocale(locale.LC_ALL)
        try:
            locale.setlocale(locale.LC_ALL, "C")
            self.assertEqual(i18n.sorted_for("uk", labels), before)
        finally:
            locale.setlocale(locale.LC_ALL, old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
