import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Clock3, Sparkles } from "lucide-react";
import { useRouter } from "../router/RouterContext";
import { useStore } from "../context/StoreContext";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./modeza";

const POPUP_INTERVAL_MS = 5 * 60 * 1000;
const LAST_POPUP_KEY = "modeza_promotion_popup_last_seen";

function getLastPopupAt(fallback: number): number {
  try {
    const stored = Number(window.localStorage.getItem(LAST_POPUP_KEY));
    return Number.isFinite(stored) ? stored : fallback;
  } catch {
    return fallback;
  }
}

function formatCountdown(endsAt: string, now: number): string {
  const milliseconds = Math.max(0, new Date(endsAt).getTime() - now);
  const seconds = Math.floor(milliseconds / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return `${days}d ${hours}h ${minutes}m ${remainingSeconds}s`;
}

export const PromotionShowcase: React.FC = () => {
  const { promotionAnnouncements } = useStore();
  const { navigate } = useRouter();
  const [now, setNow] = useState(Date.now());
  const [popupPromotion, setPopupPromotion] =
    useState<(typeof promotionAnnouncements)[number] | null>(null);
  const lastPopupFallback = useRef(0);

  const activePromotions = promotionAnnouncements.filter(
    (promotion) =>
      !promotion.endsAt || new Date(promotion.endsAt).getTime() > now,
  );

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (popupPromotion || activePromotions.length === 0) return;
    const lastPopupAt = getLastPopupAt(lastPopupFallback.current);
    if (now - lastPopupAt >= POPUP_INTERVAL_MS || lastPopupAt === 0) {
      setPopupPromotion(activePromotions[0]);
    }
  }, [activePromotions, now, popupPromotion]);

  const closePopup = () => {
    const dismissedAt = Date.now();
    lastPopupFallback.current = dismissedAt;
    try {
      window.localStorage.setItem(LAST_POPUP_KEY, String(dismissedAt));
    } catch {
      // Keep the cadence for this page session if browser storage is disabled.
    }
    setPopupPromotion(null);
  };

  if (activePromotions.length === 0) return null;

  return (
    <>
      <div
        className="promotion-marquee border-b border-[#D7B68C] bg-[#F4ECE9] text-[#5B332C]"
        aria-label="Current promotions"
        role="region"
      >
        <div className="promotion-marquee__track">
          {[0, 1].map((copy) => (
            <div
              key={copy}
              className="promotion-marquee__content"
              aria-hidden={copy === 1}
            >
              {activePromotions.map((promotion) => (
                <button
                  key={`${copy}-${promotion.id}`}
                  type="button"
                  onClick={() => navigate("/shop")}
                  className="inline-flex shrink-0 items-center gap-2 px-6 py-2 text-xs font-semibold uppercase tracking-[0.14em] hover:text-[#A2574F]"
                  tabIndex={copy === 1 ? -1 : undefined}
                >
                  <Sparkles
                    className="h-3.5 w-3.5 text-[#A2574F]"
                    aria-hidden="true"
                  />
                  <span>{promotion.badge}</span>
                  <span className="font-normal normal-case tracking-normal">
                    {promotion.name}
                  </span>
                  {promotion.code && (
                    <span className="rounded bg-white/80 px-1.5 py-0.5">
                      Code: {promotion.code}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      <Dialog
        open={popupPromotion !== null}
        onOpenChange={(open) => {
          if (!open && popupPromotion) closePopup();
        }}
      >
        {popupPromotion && (
          <DialogContent className="w-[calc(100vw-2rem)] max-h-[calc(100dvh-2rem)] max-w-md overflow-hidden border-[#E8D2C6] bg-[#FAF9F6] p-0">
            <div className="overflow-hidden rounded-2xl">
              <div className="bg-[#181716] px-5 py-7 text-center text-white sm:px-7 sm:py-8">
                <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-[#F2C1A7]">
                  <Sparkles className="h-5 w-5" aria-hidden="true" />
                </span>
                <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#F2C1A7]">
                  A MODEZA offer
                </p>
                <DialogTitle className="mt-2 line-clamp-2 break-words text-2xl text-white sm:text-3xl">
                  {popupPromotion.name}
                </DialogTitle>
                <p className="mx-auto mt-3 inline-flex max-w-full items-center justify-center truncate rounded-full bg-[#F2C1A7] px-3 py-1 text-xs font-bold uppercase tracking-wider text-[#181716]">
                  {popupPromotion.badge}
                </p>
              </div>
              <div className="px-5 py-5 text-center sm:px-7 sm:py-6">
                <DialogDescription className="line-clamp-3 break-words leading-6 [overflow-wrap:anywhere]">
                  {popupPromotion.description ||
                    "Explore this limited-time offer across our collection."}
                  {popupPromotion.code
                    ? ` Use code ${popupPromotion.code} at checkout.`
                    : ""}
                </DialogDescription>
                {popupPromotion.endsAt && (
                  <p className="mt-5 flex flex-wrap items-center justify-center gap-2 break-words text-xs font-semibold text-[#A2574F] sm:text-sm">
                    <Clock3 className="h-4 w-4" aria-hidden="true" />
                    Ends in{" "}
                    {formatCountdown(popupPromotion.endsAt, now)}
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    closePopup();
                    navigate("/shop");
                  }}
                  className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-full bg-[#181716] px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-white transition-colors hover:bg-[#A2574F] sm:px-5 sm:text-xs sm:tracking-[0.15em]"
                >
                  Shop the offer
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
};
