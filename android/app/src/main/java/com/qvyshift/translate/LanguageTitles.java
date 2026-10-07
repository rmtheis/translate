package com.qvyshift.translate;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Duplicate of selected code from https://svn.code.sf.net/p/apertium/svn/trunk/lttoolbox-java/src/org/apertium/Translator.java
 * Created by Jacob Nordfalk on 19-03-16.
 */
public class LanguageTitles {

  public static String getTitle(String id) {
    id = id.substring(id.lastIndexOf('/') + 1);
    if (id.endsWith(".mode") || id.endsWith(".jnlp"))
      id = id.substring(0, id.length() - 5);
    else if (id.endsWith(".jar") || id.endsWith(".zip"))
      id = id.substring(0, id.length() - 4);
    ArrayList<String[]> unidirectionalPairs = new ArrayList<String[]>();
    ArrayList<String[]> bidirectionalPairs = new ArrayList<String[]>();
    String pairs[] = id.split(",");
    for (int i = 0; i < pairs.length; i++) {
      String pair[] = pairs[i].split("-");
      if (pair.length < 2 || pairs.length > 1 && (pair.length > 2)) //  || pair[0].contains("_") || pair[1].contains("_")
        continue;
      for (int j = 0; j < pair.length; j++)
        pair[j] = pair[j].trim();
      boolean found = false;
      for (int j = 0; j < unidirectionalPairs.size() && !found; j++) {
        if (unidirectionalPairs.get(j)[0].equals(pair[0]) && unidirectionalPairs.get(j)[1].equals(pair[1]))
          found = true;
        else if (unidirectionalPairs.get(j)[0].equals(pair[1]) && unidirectionalPairs.get(j)[1].equals(pair[0])) {
          bidirectionalPairs.add(unidirectionalPairs.remove(j));
          found = true;
        }
      }
      if (!found)
        unidirectionalPairs.add(pair);
    }
    if (unidirectionalPairs.isEmpty() && bidirectionalPairs.isEmpty())
      return id;
    else {
      StringBuilder title = new StringBuilder();
      for (String pair[] : bidirectionalPairs) {
        if (title.length() != 0)
          title.append(", ");
        title.append(getTitleForPair(pair, true));
      }
      for (String pair[] : unidirectionalPairs) {
        if (title.length() != 0)
          title.append(", ");
        title.append(getTitleForPair(pair, false));
      }
      return title.toString();
    }
  }

  private static String getTitleForPair(String[] pair, boolean bidirectional) {
    if (pair.length == 0)
      return "";
    if (pair.length == 1)
      return pair[0];

    StringBuilder title = new StringBuilder();

    String lang[] = pair[0].split("_");
    title.append(getTitleForCode(lang[0]));
    for (int i = 1; i < lang.length; i++)
      title.append("(").append(lang[i].toUpperCase()).append(")");

    title.append(bidirectional ? " ⇆ " : " → ");

    lang = pair[1].split("_");
    title.append(getTitleForCode(lang[0]));
    for (int i = 1; i < lang.length; i++)
      title.append(" (").append(lang[i].toUpperCase()).append(")");
    for (int i = 2; i < pair.length; i++)
      title.append(" (").append(pair[i].toUpperCase()).append(")");

    return title.toString();
  }

  /**
   * The current title for a pair title saved by an older version ({@link App#PREF_lastModeTitle},
   * or a {@link TranslatorActivity#EXTRA_MODE} extra). A language that neither Locale nor
   * codeToTitle had a name for was titled by its raw code: through 1.0.12 that was hbs, so the
   * Serbo-Croatian pairs were "hbs → Macedonian", "Macedonian → hbs (SR)", ... Each side that
   * starts with a bare code gets that code's current name; anything else comes back unchanged.
   */
  public static String upgradeTitle(String title) {
    if (title == null) return null;
    for (String arrow : new String[]{" → ", " ⇆ "}) {
      int i = title.indexOf(arrow);
      if (i >= 0) {
        return upgradeLanguage(title.substring(0, i)) + arrow
            + upgradeLanguage(title.substring(i + arrow.length()));
      }
    }
    return title;
  }

  /** A bare code at the start of a title side: "hbs", "hbs (SR)", "sme(MID)". */
  private static final Pattern RAW_CODE = Pattern.compile("([a-z]{2,3})(?= ?\\(|$)");

  private static String upgradeLanguage(String side) {
    Matcher m = RAW_CODE.matcher(side);
    if (!m.lookingAt()) return side;
    return getTitleForCode(m.group(1)) + side.substring(m.end());
  }

  private static String getTitleForCode(String code) {
    String title;
    title = new Locale(code).getDisplayLanguage();
    if (code.equals(title)) {
      if (codeToTitle == null)
        initCodeToTitle();
      title = codeToTitle.get(code);
      if (title == null)
        title = code;
    }
    return title;
  }
  private static HashMap<String, String> codeToTitle;

  private static void initCodeToTitle() {
    codeToTitle = new HashMap<String, String>();

    //Trunk
    codeToTitle.put("ast", "Asturian");
    codeToTitle.put("sme", "Northern Sami");
    codeToTitle.put("nob", "Norwegian Bokmål");
    // Android's Locale has no name for the hbs macrolanguage (API 21-37, every UI language), so
    // without this the pairs read "hbs → Macedonian". Same name as iOS's PairCatalog.swift. The
    // other codes in PairCatalog.ENABLED all get a Locale name.
    codeToTitle.put("hbs", "Serbo-Croatian");

    //Incubator
    codeToTitle.put("sco", "Scots");
    codeToTitle.put("eng", "English");
    codeToTitle.put("kaz", "Kazakh");
    codeToTitle.put("tel", "Telugu");
    codeToTitle.put("eus", "Basque");
    codeToTitle.put("fin", "Finnish");
    codeToTitle.put("udm", "Udmurt");
    codeToTitle.put("kaz", "Kazakh");
    codeToTitle.put("tat", "Tatar");
    codeToTitle.put("kpv", "Komi-Zyrian");
    codeToTitle.put("mhr", "Eastern Mari");
    codeToTitle.put("mfe", "Morisyen");
    codeToTitle.put("csb", "Kashubian");
    codeToTitle.put("dsb", "Lower Sorbian");
    codeToTitle.put("hsb", "Upper Sorbian");
    codeToTitle.put("quz", "Cusco Quechua");
    codeToTitle.put("spa", "Spanish");
    codeToTitle.put("rup", "Aromanian");
    codeToTitle.put("deu", "German");
    codeToTitle.put("sma", "Southern Sami");
    codeToTitle.put("tgl", "Tagalog");
    codeToTitle.put("ceb", "Cebuano");

    //Nursery
    codeToTitle.put("ssp", "Spanish sign language");
    codeToTitle.put("smj", "Lule Sami");
    codeToTitle.put("tur", "Turkish");
    codeToTitle.put("rus", "Russian");

    //Staging
    codeToTitle.put("kir", "Kirghiz");
  }

}
