package com.qvyshift.translate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The Donate button's strings exist in every UI language, are not English there, and carry no
 * price: the only price the button may show is the one Play supplies at runtime.
 */
public class DonateStringsTest {
  private static final File RES = new File("src/main/res");
  // The thank-you title is left out: short words legitimately match across languages.
  private static final String[] DIFFER_FROM_ENGLISH = {
      "about_donate", "about_support_thanks", "donation_thanks_message"};
  private static final String[] ALL = {
      "about_donate", "about_support_thanks", "donation_thanks_title", "donation_thanks_message"};

  private static String read(File f) throws IOException {
    return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
  }

  private static String value(String xml, String name) {
    Matcher m = Pattern.compile("<string name=\"" + name + "\">(.*?)</string>", Pattern.DOTALL)
        .matcher(xml);
    return m.find() ? m.group(1) : null;
  }

  @Test
  public void everyLanguageHasItsOwnText() throws IOException {
    String english = read(new File(RES, "values/strings.xml"));
    int languages = 0;
    for (File dir : RES.listFiles()) {
      File strings = new File(dir, "strings.xml");
      if (!dir.getName().startsWith("values-") || !strings.exists()) continue;
      languages++;
      String xml = read(strings);
      for (String name : ALL) {
        assertNotNull(dir.getName() + " lacks " + name, value(xml, name));
      }
      for (String name : DIFFER_FROM_ENGLISH) {
        assertNotEquals(dir.getName() + " has English " + name,
            value(english, name), value(xml, name));
      }
    }
    assertTrue("found only " + languages + " language folders", languages >= 49);
  }

  @Test
  public void noPriceIsHardcoded() throws IOException {
    for (File dir : RES.listFiles()) {
      File strings = new File(dir, "strings.xml");
      if (!dir.getName().startsWith("values") || !strings.exists()) continue;
      String xml = read(strings);
      for (String name : ALL) {
        String text = value(xml, name);
        if (text != null) {
          assertFalse(dir.getName() + " " + name + " has a digit: " + text,
              text.matches("(?s).*\\d.*"));
        }
      }
    }
  }

  @Test
  public void rowFormatTakesLabelAndPrice() throws IOException {
    String english = read(new File(RES, "values/strings.xml"));
    assertTrue(english.contains("name=\"about_donate_row\">%1$s \\u2022 %2$s<"));
    assertEquals("support_2026", Pattern.compile(
        "name=\"support_product_id\">([^<]+)<").matcher(english).results()
        .findFirst().orElseThrow().group(1));
  }
}
