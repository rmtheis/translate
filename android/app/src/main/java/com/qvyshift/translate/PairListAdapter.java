package com.qvyshift.translate;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Filter;
import android.widget.ImageView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Dropdown adapter that groups {@link PairCatalog.Pair} directions under their
 * quality-tier headers and draws a check for locally-installed titles.
 */
public class PairListAdapter extends ArrayAdapter<PairListAdapter.Item> {

  public enum Kind { HEADER, PAIR }

  public static final class Item {
    public final Kind kind;
    public final String text;                 // header label or pair title
    public final boolean installed;           // meaningful only for PAIR
    public final PairCatalog.Pair pair;       // null for HEADER
    public final String modeTitle;            // null for HEADER — canonical title used by titleToMode

    private Item(Kind kind, String text, boolean installed, PairCatalog.Pair pair, String modeTitle) {
      this.kind = kind;
      this.text = text;
      this.installed = installed;
      this.pair = pair;
      this.modeTitle = modeTitle;
    }

    static Item header(String label) { return new Item(Kind.HEADER, label, false, null, null); }
    static Item pair(String title, boolean installed, PairCatalog.Pair p) {
      return new Item(Kind.PAIR, title, installed, p, title);
    }

    @Override
    public String toString() { return text; }
  }

  private final LayoutInflater inflater;
  private final Filter passThroughFilter = new Filter() {
    @Override
    protected FilterResults performFiltering(CharSequence constraint) {
      FilterResults results = new FilterResults();
      List<Item> all = snapshot;
      results.values = all;
      results.count = all.size();
      return results;
    }
    @Override
    protected void publishResults(CharSequence constraint, FilterResults results) {
      notifyDataSetChanged();
    }
  };
  private List<Item> snapshot;

  public PairListAdapter(Context ctx) {
    super(ctx, 0);
    this.inflater = LayoutInflater.from(ctx);
    this.snapshot = new ArrayList<>();
  }

  /** Rebuild the list from catalog + current installed-title set. */
  public void setInstalledTitles(Set<String> installedTitles) {
    Map<PairCatalog.Tier, List<Item>> byTier = new EnumMap<>(PairCatalog.Tier.class);
    for (PairCatalog.Pair p : PairCatalog.ENABLED) {
      List<Item> bucket = byTier.computeIfAbsent(p.tier, k -> new ArrayList<>());
      addDirection(bucket, p, p.forwardMode, installedTitles);
      if (p.backwardMode != null) {
        addDirection(bucket, p, p.backwardMode, installedTitles);
      }
    }

    List<Item> combined = new ArrayList<>();
    for (PairCatalog.Tier tier : PairCatalog.Tier.values()) {
      List<Item> bucket = byTier.get(tier);
      if (bucket == null || bucket.isEmpty()) continue;
      Collections.sort(bucket, Comparator.comparing(i -> i.text));
      combined.add(Item.header(getContext().getString(tier.labelRes)));
      combined.addAll(bucket);
    }

    snapshot = combined;
    clear();
    addAll(combined);
    notifyDataSetChanged();
  }

  private static void addDirection(List<Item> bucket, PairCatalog.Pair p, String mode, Set<String> installedTitles) {
    String title = LanguageTitles.getTitle(mode);
    bucket.add(Item.pair(title, installedTitles.contains(title), p));
  }

  @Override
  public int getViewTypeCount() { return 2; }

  @Override
  public int getItemViewType(int position) {
    return getItem(position).kind.ordinal();
  }

  @Override
  public boolean isEnabled(int position) {
    return getItem(position).kind == Kind.PAIR;
  }

  @Override
  public boolean areAllItemsEnabled() { return false; }

  @Override
  public View getView(int position, View convertView, ViewGroup parent) {
    Item item = getItem(position);
    if (item.kind == Kind.HEADER) {
      TextView v = (TextView) (convertView != null ? convertView
          : inflater.inflate(R.layout.item_pair_header, parent, false));
      v.setText(item.text);
      return v;
    }
    View v = convertView != null ? convertView
        : inflater.inflate(R.layout.item_pair_row, parent, false);
    ((TextView) v.findViewById(R.id.pairTitle)).setText(item.text);
    v.findViewById(R.id.installedCheck)
        .setVisibility(item.installed ? View.VISIBLE : View.INVISIBLE);
    return v;
  }

  @Override
  public Filter getFilter() { return passThroughFilter; }
}
