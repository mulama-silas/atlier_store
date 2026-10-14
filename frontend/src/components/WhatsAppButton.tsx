import React, { useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { motion } from "motion/react";

interface WhatsAppButtonProps {
  phoneNumber?: string;
  message?: string;
  className?: string;
}

const defaultPhoneNumber =
  process.env.DEFAULT_WHATSAPP_NUMBER || "+254768873844";

export const WhatsAppButton: React.FC<WhatsAppButtonProps> = ({
  phoneNumber = defaultPhoneNumber,
  message = "",
  className = "",
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const whatsappUrl = message
    ? `https://wa.me/${phoneNumber}?text=${encodeURIComponent(message)}`
    : `https://wa.me/${phoneNumber}`;

  return (
    <>
      <motion.button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={isOpen ? "Close WhatsApp" : "Open WhatsApp"}
        aria-expanded={isOpen}
        className={`
        fixed bottom-24 right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-[#25D366] text-white shadow-lg transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 ${className}
      `}
        whileTap={{ scale: 0.94 }}
      >
        {isOpen ? <X size={22} /> : <MessageCircle size={22} />}
      </motion.button>

      {isOpen && (
        <motion.aside
          key="whatsapp-panel"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.98 }}
          transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          role="dialog"
          aria-label="WhatsApp chat"
          className="fixed bottom-40 right-4 left-4 z-[60] flex h-[min(500px,70vh)] flex-col overflow-hidden rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] shadow-2xl sm:left-auto sm:right-6 sm:w-[400px]"
        >
          <div className="flex items-center justify-between border-b border-[#E8E5DF] bg-white px-4 py-3">
            <div className="flex items-center gap-2">
              <MessageCircle
                className="h-6 w-6 text-[#25D366]"
                aria-hidden="true"
              />
              <div>
                <p className="text-sm font-semibold leading-tight text-[#181716]">
                  WhatsApp
                </p>
                <p className="text-xs text-[#827E77]">Chat with us</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              aria-label="Close WhatsApp"
              className="rounded-full p-1.5 text-[#827E77] transition-colors hover:bg-[#F4ECE9] hover:text-[#181716]"
            >
              <X size={14} />
            </button>
          </div>
          <div className="flex-1 space-y-4 px-4 py-3">
            {message && (
              <div className="rounded-2xl border border-[#E8E5DF] bg-white p-3 text-sm leading-relaxed text-[#181716]">
                <p className="font-medium text-[#181716]">Message:</p>
                <textarea
                  readOnly
                  className="mt-1 rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-2 py-1.5 text-sm text-[#181716] placeholder:text-[#827E77] resize-none"
                  rows={3}
                  defaultValue={message}
                />
              </div>
            )}
            <a
              href={whatsappUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-full bg-[#25D366] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#128C49] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
            >
              <MessageCircle className="h-5 w-5" aria-hidden="true" />
              Send Message on WhatsApp
            </a>
          </div>
        </motion.aside>
      )}
    </>
  );
};
