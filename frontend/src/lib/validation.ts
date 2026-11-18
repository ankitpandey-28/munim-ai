/** Client-side validation mirroring the backend rules (the backend remains authoritative). */

export function normalizeIndianMobile(raw: string): string | null {
  let digits = raw.trim().replace(/[\s\-().]/g, "");
  if (digits.startsWith("+")) {
    digits = digits.slice(1);
    if (!digits.startsWith("91")) return null;
  }
  if (!/^\d+$/.test(digits)) return null;
  if (digits.startsWith("0091")) digits = digits.slice(4);
  else if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length !== 10 || !/^[6-9]/.test(digits)) return null;
  return `+91${digits}`;
}

export type PasswordIssue = "too_short" | "too_long" | "same_as_phone";

export function passwordIssues(password: string, phone?: string): PasswordIssue[] {
  const pw = password.normalize("NFKC");
  const issues: PasswordIssue[] = [];
  if (pw.length < 8) issues.push("too_short");
  if (pw.length > 128) issues.push("too_long");
  if (phone) {
    const digits = phone.replace(/\D/g, "");
    if (digits && (pw === digits || pw === digits.slice(-10))) issues.push("same_as_phone");
  }
  return issues;
}

export function isValidPincode(value: string): boolean {
  return /^[1-9][0-9]{5}$/.test(value);
}
