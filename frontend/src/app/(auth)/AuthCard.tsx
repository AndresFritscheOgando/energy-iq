import Link from "next/link";
import type { ReactNode } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Props = {
  id: string;
  title: string;
  description: string;
  footerText: string;
  footerLink: { href: string; label: string };
  children: ReactNode;
};

export function AuthCard({ id, title, description, footerText, footerLink, children }: Props) {
  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>
          <h1 id={id}>{title}</h1>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
      <CardFooter className="text-sm">
        <p>
          {footerText}{" "}
          <Link href={footerLink.href} className="underline underline-offset-4">
            {footerLink.label}
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
