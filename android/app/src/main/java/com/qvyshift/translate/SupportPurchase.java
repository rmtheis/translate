package com.qvyshift.translate;

import android.app.Activity;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import androidx.annotation.NonNull;

import com.android.billingclient.api.AcknowledgePurchaseParams;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClient.BillingResponseCode;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.PurchasesUpdatedListener;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryPurchasesParams;

import java.util.Collections;
import java.util.List;

/**
 * The one-time "Donate" purchase offered in the About + Settings dialog.
 *
 * One instance per process, created by {@link App} as soon as the first screen is resumed so
 * that Play's localized price is normally already known by the time the dialog opens. Until
 * Play has answered, the button shows the plain "Donate" label: no price is ever shown that Play
 * did not supply, in particular never a hardcoded dollar amount.
 *
 * The purchase unlocks nothing: the button is disabled and says thank you, that is all. Without a
 * Play Store (sideloads, emulators with no account) it stays "Donate" and a tap does nothing.
 */
public class SupportPurchase implements PurchasesUpdatedListener {
  private static final String TAG = "SupportPurchase";

  public interface Listener {
    /** Play's localized formatted price for the product, e.g. "$2.99" or "2,99 €". */
    void onPriceAvailable(String formattedPrice);

    /**
     * A completed purchase exists. justPurchased is true when it was made just now
     * (onPurchasesUpdated), false when it was found by querying purchases.
     */
    void onSupporter(boolean justPurchased);
  }

  private static SupportPurchase instance;

  /** The process-wide instance; creating it starts the Play connection and price lookup. */
  public static synchronized SupportPurchase get(Context context) {
    if (instance == null) instance = new SupportPurchase(context.getApplicationContext());
    return instance;
  }

  private final String productId;
  private final long startedAt = SystemClock.elapsedRealtime();
  private final Handler mainHandler = new Handler(Looper.getMainLooper());
  private final BillingClient client;

  // Touched on the main thread only: billing callbacks arrive on binder threads and post here.
  private String formattedPrice;
  private boolean supporter;
  private ProductDetails productDetails;
  private Listener listener;

  private SupportPurchase(Context context) {
    productId = context.getString(R.string.support_product_id);
    client = BillingClient.newBuilder(context)
        .setListener(this)
        .enablePendingPurchases(
            PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
        .enableAutoServiceReconnection()
        .build();
    connect();
  }

  private void connect() {
    int state = client.getConnectionState();
    if (state == BillingClient.ConnectionState.CONNECTED
        || state == BillingClient.ConnectionState.CONNECTING) return;
    client.startConnection(new BillingClientStateListener() {
      @Override
      public void onBillingSetupFinished(@NonNull BillingResult result) {
        if (result.getResponseCode() != BillingResponseCode.OK) {
          // No Play Store, no account, or billing unsupported: the button stays "Donate".
          Log.i(TAG, "Billing unavailable after " + elapsedMs() + " ms: " + result);
          return;
        }
        Log.i(TAG, "Billing connected after " + elapsedMs() + " ms");
        queryPurchases();
        queryProductDetails();
      }

      @Override
      public void onBillingServiceDisconnected() {
        // enableAutoServiceReconnection() reconnects on the next call.
        Log.i(TAG, "Billing service disconnected");
      }
    });
  }

  /**
   * The dialog calls this when it opens: the state known so far is replayed at once (so a cached
   * price is on screen before the first frame), later changes follow. Main thread.
   */
  public void attach(Listener l) {
    listener = l;
    if (formattedPrice != null) l.onPriceAvailable(formattedPrice);
    if (supporter) l.onSupporter(false);
    if (client.isReady()) {
      queryPurchases();  // a purchase or refund made since launch
      if (productDetails == null) queryProductDetails();
    } else {
      connect();
    }
  }

  public void detach(Listener l) {
    if (listener == l) listener = null;
  }

  /** Opens Play's purchase sheet. Returns false when billing or the product is not ready. */
  public boolean launchPurchase(Activity activity) {
    if (productDetails == null || !client.isReady()) return false;
    BillingFlowParams.ProductDetailsParams.Builder params =
        BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(productDetails);
    ProductDetails.OneTimePurchaseOfferDetails offer = offerDetails(productDetails);
    if (offer != null && offer.getOfferToken() != null && !offer.getOfferToken().isEmpty()) {
      params.setOfferToken(offer.getOfferToken());
    }
    BillingFlowParams flow = BillingFlowParams.newBuilder()
        .setProductDetailsParamsList(Collections.singletonList(params.build()))
        .build();
    BillingResult result = client.launchBillingFlow(activity, flow);
    if (result.getResponseCode() == BillingResponseCode.ITEM_ALREADY_OWNED) queryPurchases();
    return result.getResponseCode() == BillingResponseCode.OK;
  }

  private void queryProductDetails() {
    QueryProductDetailsParams.Product product = QueryProductDetailsParams.Product.newBuilder()
        .setProductId(productId)
        .setProductType(BillingClient.ProductType.INAPP)
        .build();
    QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
        .setProductList(Collections.singletonList(product))
        .build();
    client.queryProductDetailsAsync(params, (result, details) -> {
      if (result.getResponseCode() != BillingResponseCode.OK) {
        Log.d(TAG, "queryProductDetailsAsync: " + result);
        return;
      }
      for (ProductDetails match : details.getProductDetailsList()) {
        if (!productId.equals(match.getProductId())) continue;
        ProductDetails.OneTimePurchaseOfferDetails offer = offerDetails(match);
        if (offer == null) return;
        String price = offer.getFormattedPrice();
        mainHandler.post(() -> {
          productDetails = match;
          formattedPrice = price;
          Log.i(TAG, "Price " + price + " available after " + elapsedMs() + " ms");
          if (listener != null) listener.onPriceAvailable(price);
        });
        return;
      }
    });
  }

  private void queryPurchases() {
    QueryPurchasesParams params = QueryPurchasesParams.newBuilder()
        .setProductType(BillingClient.ProductType.INAPP)
        .build();
    client.queryPurchasesAsync(params, (result, purchases) -> {
      if (result.getResponseCode() == BillingResponseCode.OK) handlePurchases(purchases, false);
    });
  }

  @Override
  public void onPurchasesUpdated(@NonNull BillingResult result, List<Purchase> purchases) {
    int code = result.getResponseCode();
    if (code == BillingResponseCode.OK) {
      if (purchases != null) handlePurchases(purchases, true);
    } else if (code == BillingResponseCode.ITEM_ALREADY_OWNED) {
      queryPurchases();
    } else {
      Log.d(TAG, "onPurchasesUpdated: " + result);  // USER_CANCELED etc.
    }
  }

  private void handlePurchases(List<Purchase> purchases, boolean justPurchased) {
    for (Purchase purchase : purchases) {
      if (!purchase.getProducts().contains(productId)) continue;
      // PENDING (e.g. cash payment): nothing to show until Play completes it.
      if (purchase.getPurchaseState() != Purchase.PurchaseState.PURCHASED) continue;
      mainHandler.post(() -> {
        supporter = true;
        if (listener != null) listener.onSupporter(justPurchased);
      });
      if (!purchase.isAcknowledged()) {
        // Play refunds purchases that are not acknowledged within three days.
        AcknowledgePurchaseParams ack = AcknowledgePurchaseParams.newBuilder()
            .setPurchaseToken(purchase.getPurchaseToken())
            .build();
        client.acknowledgePurchase(ack, ackResult -> Log.d(TAG, "acknowledge: " + ackResult));
      }
    }
  }

  private static ProductDetails.OneTimePurchaseOfferDetails offerDetails(ProductDetails details) {
    List<ProductDetails.OneTimePurchaseOfferDetails> offers =
        details.getOneTimePurchaseOfferDetailsList();
    if (offers != null && !offers.isEmpty()) return offers.get(0);
    return details.getOneTimePurchaseOfferDetails();
  }

  private long elapsedMs() {
    return SystemClock.elapsedRealtime() - startedAt;
  }
}
