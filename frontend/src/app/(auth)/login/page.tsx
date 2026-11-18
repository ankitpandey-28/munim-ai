import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/auth/login-form";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Login" };

export default function LoginPage() {
  return (
    <Suspense fallback={<LoadingBlock label="…" />}>
      <LoginForm />
    </Suspense>
  );
}
