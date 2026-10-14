import React from "react";
import {
  ArrowDown,
  ArrowRight,
  Feather,
  Leaf,
  Mail,
  PackageCheck,
  RefreshCw,
  Scissors,
  ShieldCheck,
  Sparkles,
  Truck,
  Wallet,
} from "lucide-react";
import { useRouter } from "../router/RouterContext";
import { Badge, Button, Separator } from "../components/modeza";

const commitments = [
  {
    number: "01",
    title: "Choose for feel and longevity",
    text: "Traceable silk, responsible wool, and Mongolian cashmere shape a collection built around touch, drape, and repeat wear.",
  },
  {
    number: "02",
    title: "Refine the silhouette",
    text: "Fluid tailoring and considered details keep each piece expressive without tying it to a single season.",
  },
  {
    number: "03",
    title: "Make in small batches",
    text: "We work with specialist studios on limited runs, giving each design room for thoughtful development.",
  },
];

export const AboutPage: React.FC = () => {
  const { navigate } = useRouter();

  return (
    <main className="overflow-hidden bg-[#FAF9F6] text-[#181716]">
      <section
        aria-labelledby="about-title"
        className="relative isolate min-h-[680px] overflow-hidden bg-[#181716] text-white sm:min-h-[740px]"
      >
        <img
          src="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=2000&auto=format&fit=crop"
          alt="A softly tailored look from the MODEZA collection"
          className="absolute inset-0 -z-20 h-full w-full object-cover object-center opacity-65"
          referrerPolicy="no-referrer"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-gradient-to-r from-[#181716]/90 via-[#181716]/55 to-[#181716]/10"
        />
        <div
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 -z-10 h-48 bg-gradient-to-t from-[#181716]/65 to-transparent"
        />

        <div className="mx-auto flex min-h-[680px] max-w-7xl flex-col justify-between px-5 pb-10 pt-6 sm:min-h-[740px] sm:px-8 sm:pb-14 lg:px-12">
          <nav
            aria-label="About MODEZA sections"
            className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-white/25 pb-5 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/75"
          >
            <span className="text-white">The MODEZA story</span>
            <a
              href="#point-of-view"
              className="transition-colors hover:text-white"
            >
              Our point of view
            </a>
            <a
              href="#craftsmanship"
              className="transition-colors hover:text-white"
            >
              How we make
            </a>
            <a
              href="#sustainability"
              className="transition-colors hover:text-white"
            >
              Materials
            </a>
          </nav>

          <div className="max-w-3xl py-20 sm:py-24">
            <Badge
              variant="new"
              size="lg"
              className="gap-2 border-white/20 bg-white/10 text-white"
            >
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              The MODEZA point of view
            </Badge>
            <h1
              id="about-title"
              className="mt-7 max-w-3xl font-serif text-5xl font-normal leading-[1.04] text-balance sm:text-6xl lg:text-7xl"
            >
              A wardrobe with room to breathe.
            </h1>
            <p className="mt-6 max-w-xl text-sm leading-7 text-white/80 sm:text-base sm:leading-8">
              MODEZA brings together natural fibers, fluid tailoring, and
              lasting silhouettes for a more considered way to get dressed.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-5">
              <Button
                variant="primary"
                size="lg"
                onClick={() => navigate("/shop")}
                className="gap-2"
              >
                Explore the collection
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
              <a
                href="#point-of-view"
                className="inline-flex items-center gap-2 text-xs font-semibold text-white/85 transition-colors hover:text-white"
              >
                Get to know us
                <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            </div>
          </div>

          <div className="flex items-end justify-between gap-4 border-t border-white/25 pt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/65">
            <span>Natural materials · Small-batch making</span>
            <span className="hidden sm:inline">
              Designed for life beyond one season
            </span>
          </div>
        </div>
      </section>

      <section
        id="point-of-view"
        aria-labelledby="point-of-view-title"
        className="scroll-mt-8"
      >
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-16 sm:px-8 sm:py-20 lg:grid-cols-[0.85fr_1.15fr] lg:items-center lg:gap-20 lg:px-12 lg:py-28">
          <div className="max-w-xl">
            <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
              <span aria-hidden="true" className="h-px w-8 bg-[#A2574F]" />
              Our point of view
            </p>
            <h2
              id="point-of-view-title"
              className="mt-5 font-serif text-3xl font-normal leading-tight sm:text-4xl lg:text-5xl"
            >
              Less noise. More intention.
            </h2>
            <div className="mt-6 space-y-4 text-sm leading-7 text-[#63605A] sm:text-base sm:leading-8">
              <p>
                We believe getting dressed can feel both effortless and
                personal. That starts with pieces that work hard in your
                wardrobe, then rewards a closer look with thoughtful texture,
                proportion, and finish.
              </p>
              <p>
                Instead of chasing a new look every week, MODEZA develops
                trans-seasonal garments made to be worn, cared for, and returned
                to.
              </p>
            </div>
          </div>

          <figure className="relative">
            <div className="aspect-[5/4] overflow-hidden bg-[#E8E5DF]">
              <img
                src="https://images.unsplash.com/photo-1558618666-fcd25c85cd64?q=80&w=1500&auto=format&fit=crop"
                alt="Close-up of natural fabric and textile texture"
                className="h-full w-full object-cover"
                referrerPolicy="no-referrer"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-3 flex items-center justify-between gap-4 text-[10px] font-medium uppercase tracking-[0.16em] text-[#827E77]">
              <span>Considered from fiber to finish</span>
              <span>MODEZA / 01</span>
            </figcaption>
          </figure>
        </div>
      </section>

      <section
        id="sustainability"
        aria-labelledby="materials-title"
        className="scroll-mt-8 border-y border-[#E8E5DF] bg-white"
      >
        <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24">
          <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20">
            <div>
              <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
                <Leaf className="h-4 w-4" aria-hidden="true" />
                Materials with meaning
              </p>
              <h2
                id="materials-title"
                className="mt-5 max-w-md font-serif text-3xl font-normal leading-tight sm:text-4xl"
              >
                Start with what a garment is made of.
              </h2>
            </div>
            <div>
              <p className="max-w-2xl text-sm leading-7 text-[#63605A] sm:text-base sm:leading-8">
                The collection focuses on traceable silk, responsible wool, and
                Mongolian cashmere, selected for their feel, drape, and
                potential for long wear. We favor natural fibers and keep
                production runs limited so each design can be developed with
                care.
              </p>
              <div className="mt-8 grid gap-6 border-t border-[#E8E5DF] pt-6 sm:grid-cols-3 sm:gap-8">
                <Material
                  title="Silk"
                  text="Light-catching, fluid, and selected for a beautiful handfeel."
                />
                <Material
                  title="Wool"
                  text="A considered layer for warmth, structure, and everyday ease."
                />
                <Material
                  title="Cashmere"
                  text="Soft texture chosen to bring quiet comfort to the wardrobe."
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section
        id="craftsmanship"
        aria-labelledby="craftsmanship-title"
        className="scroll-mt-8 bg-[#F4ECE9]"
      >
        <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24">
          <div className="grid gap-10 lg:grid-cols-[0.75fr_1.25fr] lg:gap-20">
            <div className="max-w-md">
              <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
                <Scissors className="h-4 w-4" aria-hidden="true" />
                Craft, not excess
              </p>
              <h2
                id="craftsmanship-title"
                className="mt-5 font-serif text-3xl font-normal leading-tight sm:text-4xl"
              >
                Make fewer pieces. Give each one attention.
              </h2>
              <p className="mt-5 text-sm leading-7 text-[#63605A] sm:text-base sm:leading-8">
                We work with trusted specialist studios on small-batch
                production. Each garment is inspected before dispatch, with the
                aim of bringing considered design and dependable quality
                together.
              </p>
            </div>

            <ol className="divide-y divide-[#D8D3CB] border-y border-[#D8D3CB]">
              {commitments.map((item) => (
                <li
                  key={item.number}
                  className="grid gap-3 py-5 sm:grid-cols-[3.5rem_0.8fr_1.2fr] sm:items-start sm:gap-6 sm:py-6"
                >
                  <span className="font-serif text-2xl text-[#A2574F]">
                    {item.number}
                  </span>
                  <h3 className="font-serif text-xl font-normal leading-tight">
                    {item.title}
                  </h3>
                  <p className="text-sm leading-6 text-[#63605A]">
                    {item.text}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="client-care-title"
        className="bg-[#181716] text-[#FAF9F6]"
      >
        <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24">
          <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20">
            <div className="max-w-md">
              <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#E68057]">
                <PackageCheck className="h-4 w-4" aria-hidden="true" />
                Thoughtful service
              </p>
              <h2
                id="client-care-title"
                className="mt-5 font-serif text-3xl font-normal leading-tight sm:text-4xl"
              >
                A considered experience, all the way home.
              </h2>
              <p className="mt-5 text-sm leading-7 text-white/65">
                MODEZA serves customers across Kenya, with clear delivery
                choices, secure checkout, and a real team available when you
                need help.
              </p>
            </div>

            <div className="grid gap-x-8 sm:grid-cols-2">
              <Service
                icon={<Truck className="h-4 w-4" />}
                title="Delivery across Kenya"
                text="Standard delivery usually takes 2–4 working days in major counties; express delivery usually takes 1–2 working days."
              />
              <Service
                icon={<Wallet className="h-4 w-4" />}
                title="Ways to pay"
                text="Choose M-Pesa, card, or pay on delivery. Checkout shows your order total before you confirm."
              />
              <Service
                icon={<RefreshCw className="h-4 w-4" />}
                title="30-day returns"
                text="Return unworn, unwashed pieces in their original wrapping within 30 days of delivery."
              />
              <Service
                icon={<ShieldCheck className="h-4 w-4" />}
                title="Order with confidence"
                text="Track order milestones with your reference code, and contact our concierge for personal assistance."
              />
            </div>

            <div className="flex flex-wrap items-center gap-4 border-t border-white/15 pt-6 lg:col-start-2">
              <Button
                variant="outline"
                size="md"
                onClick={() => navigate("/shipping")}
                className="border-white/50 text-white hover:bg-white hover:text-[#181716]"
              >
                Shipping &amp; delivery
              </Button>
              <Button
                variant="outline"
                size="md"
                onClick={() => navigate("/returns")}
                className="border-white/50 text-white hover:bg-white hover:text-[#181716]"
              >
                Returns &amp; exchanges
              </Button>
              <a
                href="mailto:concierge@modeza-boutique.com"
                className="inline-flex items-center gap-2 text-xs font-semibold text-white/75 transition-colors hover:text-white"
              >
                <Mail className="h-4 w-4" aria-hidden="true" />
                Contact the concierge
              </a>
            </div>
          </div>
        </div>
      </section>

      <section
        id="careers"
        aria-labelledby="closing-title"
        className="scroll-mt-8 border-b border-[#E8E5DF]"
      >
        <div
          id="press"
          className="mx-auto flex max-w-7xl flex-col gap-7 px-5 py-14 sm:px-8 sm:py-16 lg:flex-row lg:items-end lg:justify-between lg:px-12"
        >
          <div className="max-w-2xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
              Careers, press &amp; collaborations
            </p>
            <h2
              id="closing-title"
              className="mt-4 font-serif text-3xl font-normal leading-tight sm:text-4xl"
            >
              Good things begin with a conversation.
            </h2>
            <p className="mt-4 text-sm leading-7 text-[#63605A]">
              For press enquiries, studio partnerships, or career conversations,
              write to our concierge team and tell us a little about what you
              have in mind.
            </p>
          </div>
          <Button
            variant="primary"
            size="lg"
            onClick={() => navigate("/shop")}
            className="shrink-0 gap-2"
          >
            Find your next piece
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </section>
    </main>
  );
};

const Material: React.FC<{ title: string; text: string }> = ({
  title,
  text,
}) => (
  <div>
    <h3 className="font-serif text-xl">{title}</h3>
    <p className="mt-2 text-xs leading-5 text-[#63605A]">{text}</p>
  </div>
);

const Service: React.FC<{
  icon: React.ReactNode;
  title: string;
  text: string;
}> = ({ icon, title, text }) => (
  <div className="border-b border-white/15 py-5 sm:py-6">
    <div className="flex items-center gap-3 text-[#E68057]">
      {icon}
      <h3 className="font-serif text-xl text-white">{title}</h3>
    </div>
    <p className="mt-3 text-sm leading-6 text-white/65">{text}</p>
  </div>
);
