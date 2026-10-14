import React from "react";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { useRouter } from "../router/RouterContext";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
} from "../components/modeza";

export type LegalSlug =
  | "privacy"
  | "terms"
  | "shipping"
  | "returns"
  | "cookies";

interface LegalSection {
  heading: string;
  body: string;
  bullets?: string[];
}

interface LegalDocument {
  title: string;
  eyebrow: string;
  updated: string;
  intro: string;
  sections: LegalSection[];
}

const LEGAL_DOCUMENTS: Record<LegalSlug, LegalDocument> = {
  privacy: {
    title: "Privacy Policy",
    eyebrow: "Client data & transparency",
    updated: "Last updated September 2026",
    intro:
      "MODEZA retains only the information needed to fulfil orders, deliver parcels, issue receipts, and care for its clients. This policy explains what we hold, why, and how you can control it.",
    sections: [
      {
        heading: "Information we collect",
        body: "We collect details you provide when placing an order or creating an account — including your name, email address, phone number, and delivery address. We also record browsing history (such as recently viewed pieces) on your device so you can return to items easily.",
        bullets: [
          "Account details kept in your device-local profile (this preview build stores accounts, carts, and address books locally unless a Supabase backend is configured).",
          "Order information, stored to display order status and tracking.",
          "Payment method selection. Card and M-Pesa details are handled at the gateway; we never store full card numbers.",
        ],
      },
      {
        heading: "How we use information",
        body: "Your information supports order fulfilment, delivery updates, customer service, and, with consent, private salon announcements. We do not sell personal data to third parties.",
      },
      {
        heading: "Your choices",
        body: "You can unsubscribe from salon messages at any time, clear your browsing history, and request correction or deletion of stored data by contacting concierge@modeza-boutique.com.",
      },
    ],
  },
  terms: {
    title: "Terms of Service",
    eyebrow: "Boutique shopping agreement",
    updated: "Last updated September 2026",
    intro:
      "These terms govern your use of the MODEZA boutique storefront and the purchase of our garments. By placing an order you accept these terms.",
    sections: [
      {
        heading: "Orders & pricing",
        body: "All prices are in Kenyan Shillings (KES). The final total shown at checkout includes the prevailing value-added tax, delivery, and any Privilege discount applied. An order is confirmed when you receive an order number from MODEZA.",
        bullets: [
          "Prices and availability are correct at the time of display but may change without notice.",
          "Payment methods available include M-Pesa, card, and pay on delivery.",
          "A confirmed order reserves modeza stock; cancellation is available only for pending or confirmed orders.",
        ],
      },
      {
        heading: "Eligibility",
        body: "The storefront is available to customers with a valid delivery address in Kenya. Creating an account is required to place an order so that parcels can be tracked securely.",
      },
      {
        heading: "Our responsibility",
        body: "We produce garments in small batches and inspect each piece before dispatch. Liability is limited to the value of the goods purchased; nothing in these terms limits rights that cannot be excluded by law.",
      },
    ],
  },
  shipping: {
    title: "Shipping & Delivery",
    eyebrow: "Carbon-neutral delivery",
    updated: "Last updated September 2026",
    intro:
      "Every parcel travels carbon-neutral, from artisan cutting to handover. We calculate delivery by the delivery method selected at checkout.",
    sections: [
      {
        heading: "Delivery options",
        body: "Standard delivery is charged at 20% of the cart subtotal, while express (Priority Air) delivery carries a higher fee. Delivery is complimentary on qualifying orders above the free-shipping threshold shown during checkout.",
        bullets: [
          "Standard — usually 2–4 working days within major Kenyan counties.",
          "Express Priority Air — usually 1–2 working days.",
          "Orders are shipped from our Kenyan fulfillment modeza after payment or, for pay-on-delivery, at handover.",
        ],
      },
      {
        heading: "Tracking",
        body: "Every order receives a reference code you can track at any time from Track Order. Status milestones are shown as they are confirmed by our fulfillment team — we never invent tracking events.",
      },
      {
        heading: "Delivery area",
        body: "We currently deliver across Kenya. If your county is not yet served, we will let you know before dispatch.",
      },
    ],
  },
  returns: {
    title: "Returns & Exchanges",
    eyebrow: "Complimentary 30-day returns",
    updated: "Last updated September 2026",
    intro:
      "If a piece is not right for you, return it within 30 days of delivery for a refund or exchange. Garments must be unworn, unwashed, and in their original tissue wrapping.",
    sections: [
      {
        heading: "How to return",
        body: "Contact concierge@modeza-boutique.com within 30 days of delivery and we will arrange collection. Refunds to the original payment method are issued once the garment passes inspection.",
        bullets: [
          "M-Pesa and card returns are processed to the account used for payment.",
          "Cash-on-delivery returns can be refunded to a chosen M-Pesa number.",
          "Return shipping is complimentary for standard-sized parcels.",
        ],
      },
      {
        heading: "Exchanges",
        body: "Prefer a different size or silhouette? We will prioritise an exchange before refunding, subject to availability.",
      },
      {
        heading: "Exclusions",
        body: "Altered garments, underwear, and sale pieces marked final are excluded from returns. This does not affect your statutory rights.",
      },
    ],
  },
  cookies: {
    title: "Cookie Policy",
    eyebrow: "How this storefront stores data",
    updated: "Last updated September 2026",
    intro:
      "This preview storefront keeps the smallest footprint possible. This page explains the storage we use in plain language.",
    sections: [
      {
        heading: "What we store",
        body: "Rather than third-party advertising cookies, MODEZA uses local device storage for a handful of essential conveniences:",
        bullets: [
          "Recent activity — recently viewed pieces, saved on your device only.",
          "Membership — account session, address book, and wishlist stored locally (or via your configured Supabase account).",
          "Cart persistence — so your bag survives a refresh.",
        ],
      },
      {
        heading: "No tracking for ads",
        body: "We do not install advertising or cross-site tracking cookies. Analytics, if introduced, will be privacy-conscious and declared here.",
      },
      {
        heading: "Managing storage",
        body: "You can clear storage anytime from your browser settings, or use the Clear history action on the Recently Viewed page.",
      },
    ],
  },
};

export const LegalPage: React.FC<{ slug: LegalSlug }> = ({ slug }) => {
  const { navigate } = useRouter();
  const legalDocument = LEGAL_DOCUMENTS[slug];

  return (
    <div className="bg-[#FAF9F6] pb-20">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => navigate("/")}
          className="-ml-3 text-[#63605A] hover:bg-[#F4ECE9] hover:text-[#181716] focus-visible:ring-offset-[#FAF9F6]"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to Storefront
        </Button>

        <header className="mt-8">
          <Card className="relative overflow-hidden rounded-[2rem] border-[#181716] bg-[#181716] p-0 text-[#FAF9F6] shadow-xl hover:shadow-xl">
            <img
              src="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=2200&auto=format&fit=crop"
              alt=""
              aria-hidden="true"
              className="absolute inset-0 h-full w-full object-cover object-center"
              referrerPolicy="no-referrer"
            />
            <div
              aria-hidden="true"
              className="absolute inset-0 bg-[#181716]/75"
            />
            <div className="relative z-10 px-6 py-10 sm:px-10 sm:py-12 lg:px-14 lg:py-14">
              <Badge
                variant="outline"
                size="lg"
                className="gap-2 border-white/20 bg-white/5 text-white/80 hover:bg-white/10 hover:text-white"
              >
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {legalDocument.eyebrow}
              </Badge>
              <h1 className="mt-6 max-w-3xl font-serif text-5xl font-normal leading-[1.05] tracking-tight text-balance sm:text-6xl">
                {legalDocument.title}
              </h1>
              <div className="mt-7 border-t border-white/10 pt-5">
                <p className="text-xs text-white/50">{legalDocument.updated}</p>
                <p className="mt-4 max-w-3xl text-base leading-8 text-white/70">
                  {legalDocument.intro}
                </p>
              </div>
            </div>
          </Card>
        </header>

        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start lg:gap-12">
          <div className="order-2 min-w-0 lg:order-1">
            <div className="space-y-5">
              {legalDocument.sections.map((section, index) => {
                const sectionId = `legal-section-${slug}-${index}`;
                const headingId = `${sectionId}-heading`;

                return (
                  <Card
                    key={section.heading}
                    id={sectionId}
                    className="scroll-mt-8 p-0 shadow-sm"
                    aria-labelledby={headingId}
                  >
                    <CardHeader className="flex-row items-start gap-4 p-5 sm:p-7 sm:pb-5">
                      <Badge
                        variant="outline"
                        size="sm"
                        className="mt-1 shrink-0"
                      >
                        {String(index + 1).padStart(2, "0")}
                      </Badge>
                      <CardTitle
                        id={headingId}
                        className="text-2xl font-normal tracking-tight sm:text-3xl"
                      >
                        {section.heading}
                      </CardTitle>
                    </CardHeader>
                    <Separator />
                    <CardContent className="p-5 pt-6 sm:p-7 sm:pt-6">
                      <p className="max-w-3xl text-[15px] leading-8 text-[#63605A]">
                        {section.body}
                      </p>
                      {section.bullets && (
                        <ul className="mt-6 space-y-3">
                          {section.bullets.map((bullet) => (
                            <li
                              key={bullet}
                              className="flex items-start gap-3 rounded-xl bg-[#FAF9F6] p-4 text-sm leading-7 text-[#63605A]"
                            >
                              <span
                                className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-[#A2574F]"
                                aria-hidden="true"
                              />
                              <span>{bullet}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>

            <Card className="mt-6 border-[#E8E5DF] bg-[#F4ECE9] p-0 shadow-none">
              <CardContent className="p-5 sm:p-6">
                <p className="text-sm leading-6 text-[#63605A]">
                  Questions? Contact{" "}
                  <a
                    href="mailto:concierge@modeza-boutique.com"
                    className="rounded-sm font-medium text-[#A2574F] transition-colors hover:text-[#83443D] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 focus-visible:ring-offset-[#F4ECE9]"
                  >
                    concierge@modeza-boutique.com
                  </a>
                </p>
              </CardContent>
            </Card>
          </div>

          <aside className="order-1 min-w-0 lg:order-2">
            <Card className="p-0 shadow-sm lg:sticky lg:top-8">
              <div className="border-b border-[#E8E5DF] px-5 py-4">
                <p
                  id="legal-sections-heading"
                  className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]"
                >
                  In this document
                </p>
              </div>
              <nav aria-labelledby="legal-sections-heading" className="p-3">
                <ol className="space-y-1">
                  {legalDocument.sections.map((section, index) => (
                    <li key={section.heading}>
                      <a
                        href={`#legal-section-${slug}-${index}`}
                        className="group flex items-start gap-3 rounded-xl px-3 py-3 text-sm font-medium leading-5 text-[#63605A] transition-colors hover:bg-[#F4ECE9] hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
                      >
                        <span className="mt-0.5 text-[10px] font-semibold tracking-[0.14em] text-[#C6A77A]">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span>{section.heading}</span>
                      </a>
                    </li>
                  ))}
                </ol>
              </nav>
            </Card>
          </aside>
        </div>
      </div>
    </div>
  );
};
