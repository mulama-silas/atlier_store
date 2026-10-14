import React from "react";
import { MessageCircle } from "lucide-react";
import { motion } from "motion/react";

interface WhatsAppButtonProps {
  phoneNumber?: string;
  message?: string;
  className?: string;
}

const defaultPhoneNumber =
  import.meta.env.DEFAULT_WHATSAPP_NUMBER || "+254768873844";

export const WhatsAppButton: React.FC<WhatsAppButtonProps> = ({
  phoneNumber = defaultPhoneNumber,
  message = "",
  className = "",
}) => {
  const whatsappPhoneNumber = phoneNumber.replace(/\D/g, "");
  const whatsappUrl = message
    ? `https://wa.me/${whatsappPhoneNumber}?text=${encodeURIComponent(message)}`
    : `https://wa.me/${whatsappPhoneNumber}`;

  return (
    <motion.a
      href={whatsappUrl}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Open WhatsApp chat"
      className={`
        fixed bottom-24 right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-[#25D366] text-white shadow-lg transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 ${className}
      `}
      whileTap={{ scale: 0.94 }}
    >
      <MessageCircle size={22} aria-hidden="true" />
    </motion.a>
  );
};
