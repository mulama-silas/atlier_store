export function createGmailComposeUrl(
  recipient: string,
  subject = "MODEZA enquiry",
): string {
  return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(recipient)}&su=${encodeURIComponent(subject)}`;
}
