import React from 'react';

export interface AccountPageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
}

/**
 * Editorial page header used across the customer account module:
 * small uppercase kicker, Playfair serif title, muted description.
 */
export const AccountPageHeader: React.FC<AccountPageHeaderProps> = ({
  eyebrow,
  title,
  description,
}) => (
  <header className="space-y-2.5">
    {eyebrow && (
      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#827E77]">
        {eyebrow}
      </p>
    )}
    <h1 className="font-serif text-3xl tracking-tight text-[#181716] sm:text-4xl">
      {title}
    </h1>
    {description && <p className="max-w-2xl text-sm leading-relaxed text-[#63605A]">{description}</p>}
  </header>
);
