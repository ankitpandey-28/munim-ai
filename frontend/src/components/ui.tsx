"use client";

/** Small, accessible UI primitives. Large touch targets (>= 48px) for shop-counter use. */

import { useId, useState } from "react";

export function Button({
  children,
  variant = "primary",
  loading = false,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
}) {
  const styles = {
    primary: "bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-emerald-700/60",
    secondary:
      "border border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
    danger: "bg-red-700 text-white hover:bg-red-800 disabled:bg-red-700/60",
    ghost: "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800",
  }[variant];
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-lg px-5 py-2 text-base font-medium transition disabled:cursor-not-allowed ${styles} ${className}`}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function TextField({
  label,
  hint,
  error,
  optionalLabel,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string;
  optionalLabel?: string;
}) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {optionalLabel && <span className="ml-1 font-normal text-zinc-500">({optionalLabel})</span>}
      </label>
      <input
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={`min-h-12 rounded-lg border px-3 py-2 text-base outline-none focus:ring-2 focus:ring-emerald-600 dark:bg-zinc-900 ${
          error ? "border-red-600" : "border-zinc-300 dark:border-zinc-700"
        }`}
      />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-zinc-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function SelectField({
  label,
  options,
  error,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label: string;
  options: { value: string; label: string }[];
  error?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <select
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`min-h-12 rounded-lg border bg-white px-3 py-2 text-base dark:bg-zinc-900 ${
          error ? "border-red-600" : "border-zinc-300 dark:border-zinc-700"
        }`}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function Alert({
  kind = "error",
  children,
}: {
  kind?: "error" | "success" | "info";
  children: React.ReactNode;
}) {
  const styles = {
    error: "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200",
    success:
      "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
    info: "border-zinc-300 bg-zinc-50 text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2" role={label ? "status" : undefined}>
      <span
        aria-hidden
        className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
      />
      {label && <span>{label}</span>}
    </span>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center text-zinc-500">
      <Spinner label={label} />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-300 px-6 py-10 text-center dark:border-zinc-700">
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-zinc-500">{description}</p>}
      {action}
    </div>
  );
}

export function Card({
  title,
  action,
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-zinc-200 p-4 sm:p-5 dark:border-zinc-800">
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function CheckboxField({
  label,
  hint,
  error,
  ...props
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string; hint?: string; error?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="flex min-h-12 cursor-pointer items-center gap-3 text-base">
        <input id={id} type="checkbox" {...props} className="h-5 w-5 accent-emerald-700" aria-invalid={error ? true : undefined} />
        <span>{label}</span>
      </label>
      {hint && !error && <p className="text-xs text-zinc-500">{hint}</p>}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warn" | "good" }) {
  const styles = {
    neutral: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
    good: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>{children}</span>;
}

/**
 * Two-step inline confirmation for important actions (archive, price change). Uses no browser
 * dialogs: the first press reveals the question with explicit Confirm / Cancel buttons.
 */
export function ConfirmAction({
  label,
  question,
  confirmLabel,
  cancelLabel,
  onConfirm,
  variant = "danger",
  busy = false,
}: {
  label: string;
  question: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void | Promise<void>;
  variant?: "danger" | "primary";
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button type="button" variant={variant === "danger" ? "secondary" : "primary"} onClick={() => setOpen(true)} className={variant === "danger" ? "text-red-700 dark:text-red-400" : ""}>
        {label}
      </Button>
    );
  }
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
      <div>{question}</div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant={variant}
          loading={busy}
          onClick={async () => {
            await onConfirm();
            setOpen(false);
          }}
        >
          {confirmLabel}
        </Button>
        <Button type="button" variant="secondary" onClick={() => setOpen(false)} disabled={busy}>
          {cancelLabel}
        </Button>
      </div>
    </div>
  );
}
