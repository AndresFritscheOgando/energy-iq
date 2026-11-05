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
    title: "Your properties",
    breadcrumb: "Properties",
    signedInAs: (email: string) => `Signed in as ${email}`,
    memberSince: (date: string) => `Member since ${date}`,
    listLabel: "Your properties",
    emptyTitle: "No properties yet",
    emptyBody: "Add the place where your meter is, then add the meter and your readings.",
  },

  propertyForm: {
    title: "Add a property",
    nickname: "Nickname",
    nicknameHint: "Like Home or Beach apartment.",
    nicknameRequired: "Enter a nickname.",
    region: "Region",
    submit: "Add property",
    pending: "Adding…",
    nameTaken: "This name is already in use.",
  },

  property: {
    metersTitle: "Meters",
    emptyTitle: "No meters yet",
    emptyBody: "Add the meter at this property, then start logging its readings.",
    inactive: "Inactive",
  },

  meterForm: {
    title: "Add a meter",
    label: "Label",
    labelHint: "Like Main meter or Upstairs.",
    labelRequired: "Enter a label.",
    distributor: "Distributor",
    distributorPlaceholder: "Choose a distributor",
    distributorRequired: "Choose a distributor.",
    distributorLabels: {
      EDESUR: "EDESUR",
      EDEESTE: "EDEESTE",
      EDENORTE: "EDENORTE",
      OTHER: "Other",
    },
    submit: "Add meter",
    pending: "Adding…",
    labelTaken: "This label is already in use on this property.",
    propertyGone: "This property is no longer available.",
    goHome: "Go to your properties",
  },

  optional: "(optional)",

  lists: {
    loadMore: "Load more",
    loadingMore: "Loading…",
    loading: "Loading…",
    showing: (count: number, noun: string) => `Showing ${count} ${noun}`,
    loadFailed: "That didn't load.",
    sectionFailed: (what: string) => `${what} couldn't load.`,
    retry: "Retry",
    retrying: "Retrying…",
  },

  notFound: {
    title: "We couldn't find that page.",
    link: "Go to your properties",
  },

  readingForm: {
    title: "Add a reading",
    value: "Meter value",
    valueUnit: "(kWh)",
    valueHint: "The number on your meter.",
    valueFormat: "Use digits and up to 6 decimals, like 13049.5",
    date: "Date",
    dateRequired: "Choose a date.",
    time: "Time",
    submit: "Save reading",
    pending: "Saving…",
    saved: "Reading saved",
    exists:
      "A reading already exists for this date. Add a different time, or void the existing one.",
    inactiveTitle: "This meter is no longer active",
    inactiveBody: "The reading wasn't saved. Readings can only be added to an active meter.",
    notSaved: "The reading wasn't saved. What you typed is still here.",
    warningTitle: "Lower than an earlier reading",
    warningBefore: "This is lower than your earlier reading of",
    warningLink: (value: string, date: string) => `${value} kWh on ${date}`,
    warningAfter: "If the earlier reading is wrong, void it.",
    saveAnyway: "Save anyway",
    changeValue: "Change value",
  },

  inactiveMeter: {
    marker: "Inactive",
    title: "This meter is inactive",
    body: "Readings can't be added to an inactive meter. Its usage and readings stay here.",
  },

  readings: {
    title: "Readings",
    newestFirst: "Newest first",
    noun: "readings",
    sectionName: "Readings",
    value: (value: string) => `${value} kWh`,
    emptyTitle: "No readings yet",
    emptyBody: "Add your first reading with the form on this page.",
    flagged: "Flagged",
    voided: "Voided",
    void: "Void",
    voidLabel: (value: string, date: string) => `Void ${value} kWh on ${date}`,
    voidTitle: "Void this reading?",
    voidBodyLead: (value: string, date: string) => `${value} kWh on ${date}`,
    voidBodyRest:
      " will stop counting toward usage. It stays in the list, marked Voided. This can't be undone.",
    voidCancel: "Cancel",
    voidConfirm: "Void reading",
    voidPending: "Voiding…",
    voided_announcement: (value: string, date: string) =>
      `Reading of ${value} kWh on ${date} voided.`,
    notAvailable: "Not available",
  },

  usage: {
    title: "Usage",
    rangeLabel: "Range",
    ranges: { "30d": "30 days", "90d": "90 days", "365d": "365 days" },
    rangeSentence: { "30d": "30 days", "90d": "90 days", "365d": "365 days" },
    loading: "Loading usage…",
    notAvailable: "Not available",
    errorTitle: "Usage couldn't load.",
    errorBody: "Your readings are safe, and the reading form still works.",
    retry: "Retry",
    retrying: "Retrying…",
    reference: (requestId: string) => `Reference: ${requestId}`,
    staleTitle: "Out of date",
    staleBody: (time: string) =>
      `This is usage from ${time}. It couldn't refresh, so newer readings may be missing.`,
    asOf: (time: string) => `As of ${time}`,
    needsTitle: "Add at least two readings to see usage",
    needsBody: "Usage is measured between two readings.",
    needsLink: "Go to the reading form",
    nothingTitle: (range: string) => `No usage is measured in the last ${range}.`,
    nothingLink: (range: string) => `Show the last ${range}`,
    partial: (percent: string) =>
      `${percent} of this range is measured. Gaps are marked, never counted as zero.`,
    tiles: {
      measured: "Measured",
      average: "Average per day",
      coverage: "Coverage",
      unit: "kWh",
      over: (length: string) => `Over ${length}`,
      measuredOnly: "Measured time only",
      ofRange: (range: string) => `Of the last ${range}`,
    },
    legend: {
      measured: "Measured use",
      zero: "Measured, no use",
      gap: "No measured usage",
      invalid: "Reading dropped",
    },
    yAxis: "kWh per day",
    chartLabel: "Usage chart. Use the left and right arrow keys to move through it.",
    hint: "Point at a step, or focus the chart and use arrow keys",
    kindMeasured: "Measured use",
    kindZero: "Measured, no use",
    kindGap: "No measured usage",
    kindInvalid: "Reading dropped",
    readoutStep: (span: string, rate: string, kwh: string, length: string) =>
      `${span}: ${rate} kWh per day, ${kwh} kWh, ${length}`,
    readoutBand: (span: string, length: string, reason: string) =>
      `${span}, ${length}: No measured usage. ${reason}`,
    span: (from: string, to: string) => `${from} to ${to}`,
    caption: (range: string, kwh: string, average: string, coverage: string, gaps: number) =>
      `In the last ${range}, ${kwh} kWh was measured, an average of ${average} kWh per day, with ${coverage} of the range covered. ${gaps} ${gaps === 1 ? "gap is" : "gaps are"} marked. The table below lists everything shown here.`,
    tableTitle: "Intervals and gaps",
    newestFirst: "Newest first",
    columns: {
      from: "From",
      to: "To",
      length: "Length",
      kwh: "kWh",
      rate: "kWh per day",
      note: "Note",
    },
    noMeasured: "No measured usage",
    length: {
      days: (count: string) => `${count} ${count === "1" ? "day" : "days"}`,
      hours: (count: string) => `${count} ${count === "1" ? "hour" : "hours"}`,
      underHour: "under 1 hour",
    },
    averageOver: (length: string) => `Average over ${length}`,
    reasons: {
      before_first_reading: "Before your first reading.",
      after_last_reading: "No reading yet after this date.",
      no_intervals: "Not enough readings to measure usage.",
      partial_interval:
        "A span between two readings crosses the edge of this range, so it isn't counted here. Try a longer range.",
      unexplained_decrease:
        "The reading dropped with no recorded reset or replacement, so no usage is counted.",
      flagged_reading: "A reading here is flagged, so no usage is counted.",
      unapproved_event: "A meter event here isn't approved yet, so no usage is counted.",
      meter_boundary: "The meter was reset or replaced here, so usage isn't counted across it.",
      unsupported_event: "A meter event here can't be calculated yet, so no usage is counted.",
    } as Record<string, string>,
    reasonFallback: "No measured usage here.",
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
    invalid_kwh: "Use digits and up to 6 decimals, like 13049.5",
    reading_in_future: "This can't be in the future.",
    invalid_datetime: "Enter a valid date and time.",
    datetime_out_of_range: "This date and time is out of range.",
    invalid_enum: "Choose one of the options.",
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
