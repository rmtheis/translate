package com.qvyshift.translate;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * Static catalog of every prebuilt Apertium language pair we surface in the app,
 * annotated with its quality tier. Generated from the Debian bookworm nightly index
 * at apertium.projectjj.com, cross-referenced against the apertium-{trunk,staging,
 * nursery,incubator} meta-repos on GitHub. The subset installed locally is determined
 * at runtime by {@link ApertiumInstallation}.
 *
 * TODO: regenerate from the GitHub Actions workflow when pair contents change.
 */
public final class PairCatalog {
  public enum Tier {
    TRUNK(R.string.tier_trunk),
    STAGING(R.string.tier_staging),
    NURSERY(R.string.tier_nursery),
    INCUBATOR(R.string.tier_incubator);

    public final int labelRes;
    Tier(int labelRes) { this.labelRes = labelRes; }
  }

  public static final class Pair {
    public final String pkg;
    public final String forwardMode;
    public final String backwardMode;
    public final long sizeKb;
    public final Tier tier;

    public Pair(String pkg, String forwardMode, String backwardMode, long sizeKb, Tier tier) {
      this.pkg = pkg;
      this.forwardMode = forwardMode;
      this.backwardMode = backwardMode;
      this.sizeKb = sizeKb;
      this.tier = tier;
    }
  }

  public static final List<Pair> ALL = Arrays.asList(
      new Pair("apertium-arg-cat", "arg-cat",     "cat-arg",           7_695L, Tier.TRUNK),
      new Pair("apertium-bel-rus", "bel-rus",     "rus-bel",           5_690L, Tier.TRUNK),
      new Pair("apertium-cat-ita", "cat-ita",     "ita-cat",          11_772L, Tier.TRUNK),
      new Pair("apertium-cat-srd", "cat-srd",     null,                9_516L, Tier.TRUNK),
      new Pair("apertium-dan-nor", "dan-nob",     "nob-dan",          14_865L, Tier.TRUNK),
      new Pair("apertium-eng-cat", "eng-cat",     "cat-eng",          15_851L, Tier.TRUNK),
      new Pair("apertium-eng-spa", "eng-spa",     "spa-eng",           5_466L, Tier.TRUNK),
      new Pair("apertium-fra-cat", "fra-cat",     "cat-fra",          17_268L, Tier.TRUNK),
      new Pair("apertium-hbs-eng", "hbs-eng",     "eng-hbs",           5_246L, Tier.TRUNK),
      new Pair("apertium-hbs-mkd", "hbs-mkd",     "mkd-hbs_SR",        2_889L, Tier.TRUNK),
      new Pair("apertium-mkd-eng", "mkd-eng",     null,                1_911L, Tier.TRUNK),
      new Pair("apertium-nno-nob", "nno-nob",     "nob-nno",          34_104L, Tier.TRUNK),
      new Pair("apertium-oci-cat", "oci-cat",     "cat-oci",          12_958L, Tier.TRUNK),
      new Pair("apertium-oci-fra", "oci-fra",     "fra-oci",          34_120L, Tier.TRUNK),
      new Pair("apertium-por-cat", "por-cat",     "cat-por",          14_613L, Tier.TRUNK),
      new Pair("apertium-ron-cat", "ron-cat",     "cat-ron",           9_510L, Tier.TRUNK),
      new Pair("apertium-rus-ukr", "rus-ukr",     "ukr-rus",           5_092L, Tier.TRUNK),
      new Pair("apertium-sme-nob", "sme-nob",     null,               90_300L, Tier.TRUNK),
      new Pair("apertium-spa-arg", "spa-arg",     "arg-spa",           5_366L, Tier.TRUNK),
      new Pair("apertium-spa-ast", "spa-ast",     null,                5_582L, Tier.TRUNK),
      new Pair("apertium-spa-cat", "spa-cat",     "cat-spa",          19_470L, Tier.TRUNK),
      new Pair("apertium-spa-glg", "spa-glg",     "glg-spa",          12_142L, Tier.TRUNK),
      new Pair("apertium-spa-ita", "spa-ita",     "ita-spa",           5_488L, Tier.TRUNK),
      new Pair("apertium-srd-ita", "srd-ita",     "ita-srd",           8_029L, Tier.TRUNK),
      new Pair("apertium-swe-dan", "swe-dan",     "dan-swe",           9_581L, Tier.TRUNK),
      new Pair("apertium-swe-nor", "swe-nob",     "nob-swe",          21_335L, Tier.TRUNK),
      new Pair("apertium-cat-glg", "cat-glg",     null,                8_317L, Tier.STAGING),
      new Pair("apertium-eng-deu", "eng-deu",     "deu-eng",           7_418L, Tier.NURSERY),
      new Pair("apertium-fra-ita", "fra-ita",     "ita-fra",           5_251L, Tier.NURSERY),
      new Pair("apertium-nor-eng", "nob-eng",     "eng-nob",          13_834L, Tier.NURSERY),
      new Pair("apertium-quz-spa", "quz-spa",     "spa-quz",           3_933L, Tier.NURSERY),
      new Pair("apertium-sme-fin", "sme-fin",     "fin-sme",         188_189L, Tier.NURSERY),
      new Pair("apertium-sme-sma", "sme-sma_Mid", "sma-sme",         170_026L, Tier.NURSERY),
      new Pair("apertium-sme-smj", "sme-smj",     "smj-sme",         312_410L, Tier.NURSERY),
      new Pair("apertium-sme-smn", "sme-smn",     "smn-sme",         180_296L, Tier.NURSERY),
      new Pair("apertium-afr-deu", "afr-deu",     "deu-afr",           1_397L, Tier.INCUBATOR),
      new Pair("apertium-azz-nhi", "azz-nhi",     "nhi-azz",           1_277L, Tier.INCUBATOR),
      new Pair("apertium-bho-hin", "bho-hin",     "hin-bho",             405L, Tier.INCUBATOR),
      new Pair("apertium-cat-ina", "cat-ina",     "ina-cat",           5_299L, Tier.INCUBATOR),
      new Pair("apertium-ckb-eng", "ckb-eng",     "eng-ckb",           1_323L, Tier.INCUBATOR),
      new Pair("apertium-cos-ita", "cos-ita",     null,                1_421L, Tier.INCUBATOR),
      new Pair("apertium-cos-por", "cos-por",     "por-cos",           1_031L, Tier.INCUBATOR),
      new Pair("apertium-deu-dan", "deu-dan",     "dan-deu",           4_229L, Tier.INCUBATOR),
      new Pair("apertium-deu-ina", "deu-ina",     "ina-deu",           1_327L, Tier.INCUBATOR),
      new Pair("apertium-deu-nld", "deu-nld",     "nld-deu",           2_801L, Tier.INCUBATOR),
      new Pair("apertium-dzo-eng", "dzo-eng",     "eng-dzo",           1_152L, Tier.INCUBATOR),
      new Pair("apertium-ell-eng", "ell-eng",     "eng-ell",           1_451L, Tier.INCUBATOR),
      new Pair("apertium-eng-ibo", "eng-ibo",     "ibo-eng",           1_149L, Tier.INCUBATOR),
      new Pair("apertium-eng-ina", "eng-ina",     "ina-eng",           1_238L, Tier.INCUBATOR),
      new Pair("apertium-eng-ita", "eng-ita",     "ita-eng",           6_031L, Tier.INCUBATOR),
      new Pair("apertium-eng-kir", "eng-kir",     "kir-eng",           1_935L, Tier.INCUBATOR),
      new Pair("apertium-eng-lin", "eng-lin",     "lin-eng",           1_857L, Tier.INCUBATOR),
      new Pair("apertium-eng-sco", "eng-sco",     "sco-eng",           1_464L, Tier.INCUBATOR),
      new Pair("apertium-fao-dan", "fao-dan",     "dan-fao",          13_384L, Tier.INCUBATOR),
      new Pair("apertium-fin-est", "fin-est",     "est-fin",          62_962L, Tier.INCUBATOR),
      new Pair("apertium-fin-fkv", "fin-fkv",     "fkv-fin",          69_237L, Tier.INCUBATOR),
      new Pair("apertium-fin-fra", "fin-fra",     "fra-fin",          76_915L, Tier.INCUBATOR),
      new Pair("apertium-fin-hbs", "fin-hbs",     "hbs-fin",          78_126L, Tier.INCUBATOR),
      new Pair("apertium-fin-hun", "fin-hun",     "hun-fin",          78_133L, Tier.INCUBATOR),
      new Pair("apertium-fin-isl", "fin-isl",     "isl-fin",          76_662L, Tier.INCUBATOR),
      new Pair("apertium-fin-kaz", "fin-kaz",     "kaz-fin",          76_764L, Tier.INCUBATOR),
      new Pair("apertium-fin-olo", "fin-olo",     "olo-fin",          84_624L, Tier.INCUBATOR),
      new Pair("apertium-fin-por", "fin-por",     "por-fin",          76_756L, Tier.INCUBATOR),
      new Pair("apertium-fin-rus", "fin-rus",     "rus-fin",          78_674L, Tier.INCUBATOR),
      new Pair("apertium-fin-smn", "fin-smn",     "smn-fin",         238_532L, Tier.INCUBATOR),
      new Pair("apertium-fin-spa", "fin-spa",     "spa-fin",          79_199L, Tier.INCUBATOR),
      new Pair("apertium-fin-swe", "fin-swe",     "swe-fin",          79_614L, Tier.INCUBATOR),
      new Pair("apertium-fra-eng", "fra-eng",     "eng-fra",           5_819L, Tier.INCUBATOR),
      new Pair("apertium-fra-frp", "fra-frp",     "frp-fra",          14_226L, Tier.INCUBATOR),
      new Pair("apertium-fra-ina", "fra-ina",     "ina-fra",           2_602L, Tier.INCUBATOR),
      new Pair("apertium-gle-eng", "gle-eng",     "eng-gle",          33_414L, Tier.INCUBATOR),
      new Pair("apertium-grn-spa", "grn-spa",     "spa-grn",          19_628L, Tier.INCUBATOR),
      new Pair("apertium-haw-eng", "haw-eng",     "eng-haw",           1_139L, Tier.INCUBATOR),
      new Pair("apertium-hbo-eng", "hbo-eng",     "eng-hbo",           1_744L, Tier.INCUBATOR),
      new Pair("apertium-ina-spa", "ina-spa",     "spa-ina",           3_405L, Tier.INCUBATOR),
      new Pair("apertium-ind-eng", "ind-eng",     "eng-ind",           1_248L, Tier.INCUBATOR),
      new Pair("apertium-ita-nor", "ita-nob",     "nob-ita",          18_541L, Tier.INCUBATOR),
      new Pair("apertium-kaz-tyv", "kaz-tyv",     "tyv-kaz",           1_419L, Tier.INCUBATOR),
      new Pair("apertium-kok-hin", "kok-hin",     "hin-kok",           1_830L, Tier.INCUBATOR),
      new Pair("apertium-kpv-fin", "kpv-fin",     "fin-kpv",          74_318L, Tier.INCUBATOR),
      new Pair("apertium-kpv-koi", "kpv-koi",     "koi-kpv",          32_118L, Tier.INCUBATOR),
      new Pair("apertium-lat-eng", "lat-eng",     "eng-lat",           1_261L, Tier.INCUBATOR),
      new Pair("apertium-mag-eng", "mag-eng",     "eng-mag_Lat",       1_408L, Tier.INCUBATOR),
      new Pair("apertium-mlt-spa", "mlt-spa",     null,                6_096L, Tier.INCUBATOR),
      new Pair("apertium-mrj-fin", "mrj-fin",     "fin-mrj",          66_811L, Tier.INCUBATOR),
      new Pair("apertium-mrj-mhr", "mrj-mhr",     "mhr-mrj",          92_045L, Tier.INCUBATOR),
      new Pair("apertium-myv-fin", "myv-fin",     "fin-myv",         121_614L, Tier.INCUBATOR),
      new Pair("apertium-myv-mdf", "myv-mdf",     "mdf-myv",          95_000L, Tier.INCUBATOR),
      new Pair("apertium-nor-ukr", "nob-ukr",     "ukr-nob",          22_130L, Tier.INCUBATOR),
      new Pair("apertium-por-ina", "por-ina",     "ina-por",           1_029L, Tier.INCUBATOR),
      new Pair("apertium-quc-spa", "quc-spa",     null,                5_011L, Tier.INCUBATOR),
      new Pair("apertium-slv-ita", "slv-ita",     "ita-slv",           1_466L, Tier.INCUBATOR),
      new Pair("apertium-sme-deu", "sme-deu",     "deu-sme",          80_078L, Tier.INCUBATOR),
      new Pair("apertium-sme-est", "sme-est",     "est-sme",         106_720L, Tier.INCUBATOR),
      new Pair("apertium-smj-nob", "smj-nob",     null,               57_285L, Tier.INCUBATOR),
      new Pair("apertium-spa-cos", "spa-cos",     "cos-spa",           3_317L, Tier.INCUBATOR),
      new Pair("apertium-spa-lvs", "spa-lvs",     "lvs-spa",           3_364L, Tier.INCUBATOR),
      new Pair("apertium-spa-ote", "spa-ote",     "ote-spa",           4_082L, Tier.INCUBATOR),
      new Pair("apertium-spa-pol", "spa-pol",     "pol-spa",           3_685L, Tier.INCUBATOR),
      new Pair("apertium-swe-eng", "swe-eng",     "eng-swe",           3_589L, Tier.INCUBATOR),
      new Pair("apertium-tam-eng", "tam-eng",     "eng-tam",           1_149L, Tier.INCUBATOR),
      new Pair("apertium-tat-eng", "tat-eng",     "eng-tat",           4_305L, Tier.INCUBATOR),
      new Pair("apertium-tlh-swe", "tlh-swe",     "swe-tlh",           2_303L, Tier.INCUBATOR),
      new Pair("apertium-tur-fin", "tur-fin",     "fin-tur",          23_697L, Tier.INCUBATOR),
      new Pair("apertium-udm-kpv", "udm-kpv",     "kpv-udm",          36_273L, Tier.INCUBATOR),
      new Pair("apertium-uum-eng", "uum-eng",     "eng-uum",           1_498L, Tier.INCUBATOR),
      new Pair("apertium-uum-ukr", "uum-ukr",     "ukr-uum",           1_847L, Tier.INCUBATOR),
      new Pair("apertium-uzb-kaa", "uzb-kaa",     "kaa-uzb",           3_502L, Tier.INCUBATOR),
      new Pair("apertium-vro-est", "vro-est",     "est-vro",          58_221L, Tier.INCUBATOR)
  );

  /** Pairs the app actually ships. Trunk + Staging only for now; Nursery + Incubator are future scope. */
  public static final List<Pair> ENABLED;
  static {
    List<Pair> filtered = new ArrayList<>();
    for (Pair p : ALL) {
      if (p.tier != Tier.TRUNK && p.tier != Tier.STAGING) continue;
      filtered.add(p);
    }
    ENABLED = Collections.unmodifiableList(filtered);
  }

  /** Play Asset Delivery pack name for a given pair package (e.g. apertium-eng-spa → pair_eng_spa). */
  public static String packNameFor(Pair pair) {
    return "pair_" + pair.pkg.substring("apertium-".length()).replace('-', '_');
  }

  private PairCatalog() {}
}
