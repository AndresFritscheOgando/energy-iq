import { CredentialsForm } from "@/components/auth/CredentialsForm";
import { redirectIfSignedIn } from "@/lib/api/server";
import { en } from "@/messages/en";

import { AuthCard } from "../AuthCard";

export default async function RegisterPage() {
  await redirectIfSignedIn();

  return (
    <AuthCard
      id="register-title"
      title={en.register.title}
      description={en.register.description}
      footerText={en.register.haveAccount}
      footerLink={{ href: "/login", label: en.register.loginLink }}
    >
      <CredentialsForm mode="register" next="/" />
    </AuthCard>
  );
}
