package com.qvyshift.sardu;

/** The two translation directions of the apertium-srd-ita pair. */
public enum Direction {
    SRD_TO_ITA("srd-ita", R.string.lang_sardinian, R.string.lang_italian),
    ITA_TO_SRD("ita-srd", R.string.lang_italian, R.string.lang_sardinian);

    /** Apertium mode id; also the basename of the .mode file. */
    public final String modeId;
    public final int sourceLabel;
    public final int targetLabel;

    Direction(String modeId, int sourceLabel, int targetLabel) {
        this.modeId = modeId;
        this.sourceLabel = sourceLabel;
        this.targetLabel = targetLabel;
    }

    public Direction reversed() {
        return this == SRD_TO_ITA ? ITA_TO_SRD : SRD_TO_ITA;
    }
}
