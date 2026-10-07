package com.qvyshift.translate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * getTitle() asks Locale for a name first, and the JVM's names differ from Android's (JDK 17 has
 * none for "fra", "mkd" or "ron"; Android has), so these tests pin only what doesn't depend on
 * them: the codeToTitle fallback for hbs and how old titles map to current ones.
 */
public class LanguageTitlesTest {

  private Locale defaultLocale;

  @Before
  public void useEnglishNames() {
    defaultLocale = Locale.getDefault();
    Locale.setDefault(Locale.US);
  }

  @After
  public void restoreLocale() {
    Locale.setDefault(defaultLocale);
  }

  @Test
  public void namesSerboCroatian() {
    assertEquals("Serbo-Croatian → English", LanguageTitles.getTitle("hbs-eng"));
    assertEquals("English → Serbo-Croatian", LanguageTitles.getTitle("eng-hbs"));
    String mkd = sideOf(LanguageTitles.getTitle("mkd-eng"), 0);
    assertEquals("Serbo-Croatian → " + mkd, LanguageTitles.getTitle("hbs-mkd"));
    assertEquals(mkd + " → Serbo-Croatian (SR)", LanguageTitles.getTitle("mkd-hbs_SR"));
  }

  @Test
  public void upgradesTitlesSavedWithTheRawHbsCode() {
    assertEquals("Serbo-Croatian → Macedonian", LanguageTitles.upgradeTitle("hbs → Macedonian"));
    assertEquals("Macedonian → Serbo-Croatian (SR)",
        LanguageTitles.upgradeTitle("Macedonian → hbs (SR)"));
    assertEquals("Serbo-Croatian → English", LanguageTitles.upgradeTitle("hbs → English"));
    assertEquals("English → Serbo-Croatian", LanguageTitles.upgradeTitle("English → hbs"));
    assertEquals("Serbo-Croatian(SR) → Macedonian", LanguageTitles.upgradeTitle("hbs(SR) → Macedonian"));
    assertEquals("Serbo-Croatian ⇆ English", LanguageTitles.upgradeTitle("hbs ⇆ English"));
  }

  /** What 1.0.12 showed (and saved) for each offered direction maps to today's title. */
  @Test
  public void everyOldHbsTitleUpgradesToTheCurrentTitle() {
    int hbs = 0;
    for (String mode : enabledModes()) {
      String title = LanguageTitles.getTitle(mode);
      if (!mode.contains("hbs")) continue;
      hbs++;
      String old = title.replace("Serbo-Croatian", "hbs");
      assertEquals(mode, title, LanguageTitles.upgradeTitle(old));
    }
    assertEquals(4, hbs);
  }

  @Test
  public void leavesCurrentTitlesAlone() {
    List<String> modes = enabledModes();
    assertEquals(49, modes.size());
    for (String mode : modes) {
      String title = LanguageTitles.getTitle(mode);
      assertEquals(mode, title, LanguageTitles.upgradeTitle(title));
    }
    assertEquals("English → Spanish", LanguageTitles.upgradeTitle("English → Spanish"));
    assertEquals("Northern Sami → Norwegian Bokmål",
        LanguageTitles.upgradeTitle("Northern Sami → Norwegian Bokmål"));
    assertEquals("anglais → espagnol", LanguageTitles.upgradeTitle("anglais → espagnol"));
    assertEquals("hbs", LanguageTitles.upgradeTitle("hbs"));
    assertEquals("", LanguageTitles.upgradeTitle(""));
    assertNull(LanguageTitles.upgradeTitle(null));
  }

  /** Every direction the dropdown offers, as {@link PairListAdapter} lists them. */
  private static List<String> enabledModes() {
    List<String> modes = new ArrayList<>();
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      modes.add(p.forwardMode);
      if (p.backwardMode != null) modes.add(p.backwardMode);
    }
    return modes;
  }

  private static String sideOf(String title, int side) {
    return title.split(" → ")[side];
  }
}
