import React from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Mail,
  MessageCircle,
  PackageSearch,
  RefreshCw,
  Truck,
} from "lucide-react";
import { Button } from "../components/modeza/Button";
import { useRouter } from "../router/RouterContext";

const helpLinks = [
  {
    icon: PackageSearch,
    title: "Track an order",
    description: "Check your order status and delivery milestones.",
    path: "/track",
  },
  {
    icon: Truck,
    title: "Shipping & delivery",
    description: "See delivery options, locations, and estimated times.",
    path: "/shipping",
  },
  {
    icon: RefreshCw,
    title: "Returns & exchanges",
    description: "Review the return window and how to arrange a return.",
    path: "/returns",
  },
];

const emailAddress = "boutique.modeza.support@gmail.com";
const emailComposeUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(emailAddress)}&su=${encodeURIComponent("MODEZA enquiry")}`;

export const ContactPage: React.FC = () => {
  const { navigate } = useRouter();
  const whatsappNumber = (
    import.meta.env.DEFAULT_WHATSAPP_NUMBER || "+254768873844"
  ).replace(/\D/g, "");
  const whatsappMessage = encodeURIComponent(
    "Hello MODEZA, I would like some help with my order or a product.",
  );

  return (
    <main className="bg-[#FAF9F6] text-[#181716]">
      <section
        aria-labelledby="contact-title"
        className="relative isolate overflow-hidden border-b border-[#E8E5DF] bg-[#181716] text-white"
      >
        <img
          src="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=2200&auto=format&fit=crop"
          alt=""
          aria-hidden="true"
          className="absolute inset-0 -z-20 h-full w-full object-cover object-center"
          referrerPolicy="no-referrer"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-[#181716]/70"
        />
        <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8 sm:py-20 lg:px-12 lg:py-24">
          <div className="max-w-3xl">
            <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#F2C1A7]">
              <span aria-hidden="true" className="h-px w-8 bg-[#F2C1A7]" />
              The MODEZA concierge
            </p>
            <h1
              id="contact-title"
              className="mt-5 font-serif text-4xl font-normal leading-[1.08] text-balance sm:text-5xl lg:text-6xl"
            >
              We’re here for the details.
            </h1>
            <p className="mt-5 max-w-xl text-sm leading-7 text-white/80 sm:text-base sm:leading-8">
              Questions about fit, an order, or finding the right piece? Get in
              touch with our team and we’ll help you find your way.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg" className="gap-2">
                <a
                  href={emailComposeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Mail className="h-4 w-4" aria-hidden="true" />
                  Email the concierge
                </a>
              </Button>
              <Button
                asChild
                variant="outline"
                size="lg"
                className="gap-2 border-white/70 text-white hover:bg-white hover:text-[#181716]"
              >
                <a
                  href={`https://wa.me/${whatsappNumber}?text=${whatsappMessage}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <MessageCircle className="h-4 w-4" aria-hidden="true" />
                  WhatsApp
                  <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              </Button>
            </div>
            <p className="mt-4 text-xs leading-5 text-white/65">
              For order questions, include your order number so we can direct
              you faster.
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="contact-options-title" className="bg-white">
        <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8 sm:py-16 lg:px-12 lg:py-20">
          <div className="grid gap-8 border-b border-[#E8E5DF] pb-7 sm:grid-cols-[1fr_auto] sm:items-end">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
                Speak with us
              </p>
              <h2
                id="contact-options-title"
                className="mt-3 font-serif text-3xl font-normal sm:text-4xl"
              >
                Choose what works for you.
              </h2>
            </div>
            <a
              href={emailComposeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-medium text-[#181716] underline decoration-[#C6A77A] underline-offset-4 transition-colors hover:text-[#A2574F]"
            >
              {emailAddress}
            </a>
          </div>

          <div className="grid gap-8 pt-2 md:grid-cols-2 md:gap-12">
            <div className="border-b border-[#E8E5DF] py-6 md:border-b-0">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
                <Mail className="h-4 w-4" aria-hidden="true" />
              </span>
              <h3 className="mt-5 font-serif text-2xl">Write to us</h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-[#63605A]">
                Send a note about sizing, product details, an order, or anything
                else you need help with.
              </p>
              <a
                href={emailComposeUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-5 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#A2574F] hover:text-[#83443D]"
              >
                Start an email{" "}
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            </div>

            <div className="py-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#EAF4EE] text-[#28734A]">
                <MessageCircle className="h-4 w-4" aria-hidden="true" />
              </span>
              <h3 className="mt-5 font-serif text-2xl">Chat on WhatsApp</h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-[#63605A]">
                Prefer a quick conversation? Message the MODEZA team directly
                from your device.
              </p>
              <a
                href={`https://wa.me/${whatsappNumber}?text=${whatsappMessage}`}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-5 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#28734A] hover:text-[#1F5B3A]"
              >
                Open WhatsApp{" "}
                <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            </div>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="quick-help-title"
        className="border-t border-[#E8E5DF] bg-[#F4ECE9]"
      >
        <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8 sm:py-16 lg:px-12 lg:py-20">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
                Quick help
              </p>
              <h2
                id="quick-help-title"
                className="mt-3 font-serif text-3xl font-normal sm:text-4xl"
              >
                Looking for an answer?
              </h2>
            </div>
            <p className="max-w-md text-sm leading-6 text-[#63605A]">
              These pages cover the most common order and delivery questions.
            </p>
          </div>

          <div className="mt-8 divide-y divide-[#D8D3CB] border-y border-[#D8D3CB]">
            {helpLinks.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => navigate(item.path)}
                  className="group flex w-full items-center gap-4 py-5 text-left transition-colors hover:text-[#A2574F] sm:gap-6 sm:py-6"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-[#A2574F]">
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-serif text-xl text-[#181716] sm:text-2xl">
                      {item.title}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-[#63605A] sm:text-sm">
                      {item.description}
                    </span>
                  </span>
                  <ArrowRight
                    className="h-4 w-4 shrink-0 text-[#A2574F] transition-transform group-hover:translate-x-1"
                    aria-hidden="true"
                  />
                </button>
              );
            })}
          </div>
        </div>
      </section>
    </main>
  );
};
