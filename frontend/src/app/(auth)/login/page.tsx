import { CredentialsForm } from "@/components/auth/CredentialsForm";
import { redirectIfSignedIn } from "@/lib/api/server";
import { safeNextPath } from "@/lib/safe-next";
import { en } from "@/messages/en";

import { AuthCard } from "../AuthCard";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  await redirectIfSignedIn();
  const { next } = await searchParams;
  const target = safeNextPath(typeof next === "string" ? next : null);

  return (
    <AuthCard
      id="login-title"
      title={en.login.title}
      description={en.login.description}
      footerText={en.login.noAccount}
      footerLink={{ href: "/register", label: en.login.registerLink }}
    >
      <CredentialsForm mode="login" next={target} />
    </AuthCard>
  );
}
