import React from "react";
import { ArrowRight, Mail, MessageCircle } from "lucide-react";
import { useRouter } from "../router/RouterContext";
import { createGmailComposeUrl } from "../utils/email";

const footerGroups = [
  {
    title: "Explore",
    links: [
      { label: "Shop all", path: "/shop" },
      { label: "New arrivals", path: "/shop?collection=new-arrivals" },
      { label: "Best sellers", path: "/shop?collection=best-sellers" },
      { label: "Our story", path: "/about" },
    ],
  },
  {
    title: "Customer care",
    links: [
      { label: "Contact us", path: "/contact" },
      { label: "Track an order", path: "/track" },
      { label: "Shipping & delivery", path: "/shipping" },
      { label: "Returns & exchanges", path: "/returns" },
    ],
  },
  {
    title: "Information",
    links: [
      { label: "Privacy policy", path: "/privacy" },
      { label: "Terms of service", path: "/terms" },
      { label: "Cookie policy", path: "/cookies" },
    ],
  },
];

export const Footer: React.FC = () => {
  const { navigate } = useRouter();
  const whatsappNumber = (
    import.meta.env.DEFAULT_WHATSAPP_NUMBER || "+254768873844"
  ).replace(/\D/g, "");

  return (
    <footer className="border-t border-[#E8E5DF] bg-white">
      <div className="mx-auto max-w-7xl px-5 py-12 sm:px-8 sm:py-14 lg:px-12">
        <div className="grid gap-10 border-b border-[#E8E5DF] pb-10 md:grid-cols-[1.4fr_2fr] md:gap-12 lg:pb-12">
          <div className="max-w-sm">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="rounded-sm text-left font-serif text-3xl text-[#181716] transition-colors hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-4"
            >
              MODEZA
            </button>
            <p className="mt-3 text-sm leading-6 text-[#63605A]">
              Considered clothing in natural fibers and lasting silhouettes,
              made for the life you live in it.
            </p>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-3">
              <a
                href={createGmailComposeUrl("concierge@modeza-boutique.com")}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-xs font-medium text-[#63605A] transition-colors hover:text-[#A2574F]"
              >
                <Mail
                  className="h-3.5 w-3.5 text-[#A2574F]"
                  aria-hidden="true"
                />
                Email concierge
              </a>
              <a
                href={`https://wa.me/${whatsappNumber}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-xs font-medium text-[#63605A] transition-colors hover:text-[#28734A]"
              >
                <MessageCircle
                  className="h-3.5 w-3.5 text-[#28734A]"
                  aria-hidden="true"
                />
                WhatsApp
              </a>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3 sm:gap-x-8">
            {footerGroups.map((group) => (
              <nav key={group.title} aria-label={group.title}>
                <h2 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#181716]">
                  {group.title}
                </h2>
                <ul className="mt-4 space-y-3">
                  {group.links.map((link) => (
                    <li key={link.path}>
                      <button
                        type="button"
                        onClick={() => navigate(link.path)}
                        className="group inline-flex items-center gap-1.5 text-left text-xs text-[#63605A] transition-colors hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
                      >
                        {link.label}
                        <ArrowRight
                          className="h-3 w-3 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3 pt-5 text-[11px] text-[#827E77] sm:flex-row sm:items-center sm:justify-between">
          <p>&copy; {new Date().getFullYear()} MODEZA. All rights reserved.</p>
          <p>Made for considered everyday dressing.</p>
        </div>
      </div>
    </footer>
  );
};
