/**
 * Every user facing string (spec 0010 AC-16). Server `message` text from a
 * problem body is never shown; field errors come from `fieldErrors` keyed
 * by the problem's error `code`.
 */
export const en = {
  appName: "EnergyIQ",
  metaDescription: "Your home electricity, measured and explained.",

  fields: {
    email: "Email",
    password: "Password",
  },

  login: {
    title: "Sign in",
    description: "Sign in to see your electricity readings.",
    submit: "Sign in",
    pending: "Signing in…",
    invalidCredentials: "Email or password is incorrect.",
    noAccount: "No account yet?",
    registerLink: "Create one",
  },

  register: {
    title: "Create your account",
    description: "Use your email and a password of 12 to 128 characters.",
    submit: "Create account",
    pending: "Creating account…",
    passwordHint: (length: number) =>
      `Use 12 to 128 characters. You have ${length} ${length === 1 ? "character" : "characters"}.`,
    emailTaken: "An account with this email already exists.",
    signInInstead: "Sign in instead",
    haveAccount: "Already have an account?",
    loginLink: "Sign in",
  },

  home: {
    title: "Home",
    signedInAs: (email: string) => `Signed in as ${email}`,
    memberSince: (date: string) => `Member since ${date}`,
  },

  signOut: {
    submit: "Sign out",
    pending: "Signing out…",
  },

  required: {
    email: "Enter your email.",
    password: "Enter your password.",
  },

  /** Copy per backend validation error `code`. */
  fieldErrors: {
    invalid_email: "Enter an email address, like name@example.com.",
    password_length: "Use 12 to 128 characters.",
    missing: "This field is required.",
    invalid_type: "This value is not valid.",
    invalid_text_length: "This value is too short or too long.",
  } as Record<string, string>,
  fieldErrorFallback: "This value is not valid.",

  tooManyAttempts: (minutes: number | null) =>
    minutes === null
      ? "Too many attempts. Try again later."
      : `Too many attempts. Try again in ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`,

  unavailable: {
    message: "EnergyIQ can't reach its server right now.",
    reference: (requestId: string) => `Reference: ${requestId}`,
    retry: "Retry",
    retrying: "Retrying…",
  },

  csrfRejected: {
    development: (suggestedOrigin: string | null) =>
      suggestedOrigin === null
        ? "This page was opened from an address EnergyIQ does not trust. Add it to ENERGYIQ_TRUSTED_ORIGINS and restart the API."
        : `This page was opened from an address EnergyIQ does not trust. Open ${suggestedOrigin}, or add this address to ENERGYIQ_TRUSTED_ORIGINS and restart the API.`,
    production: "Your request was blocked for your security. Reload the page and try again.",
  },

  fallback: (requestId: string | null) =>
    requestId === null ? "Something went wrong." : `Something went wrong. Reference: ${requestId}.`,

  unexpected: {
    message: "Something went wrong. Try again.",
    reference: (digest: string) => `Reference: ${digest}`,
    retry: "Retry",
  },
} as const;
