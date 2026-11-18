import Link from "next/link";
import { LanguageSelect } from "@/components/language-select";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <div className="mb-6 flex w-full max-w-sm items-center justify-between">
        <Link href="/" className="text-xl font-semibold tracking-tight">
          Munim AI
        </Link>
        <LanguageSelect compact />
      </div>
      <div className="w-full max-w-sm rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">{children}</div>
    </main>
  );
}
