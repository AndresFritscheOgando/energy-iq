import { cn } from "cn";
import type * as React from "react";

/** A native `<select>` styled with the input tokens (spec 0011 child 0001). */
function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-11 w-full min-w-0 rounded-md border border-input bg-transparent px-2.5 text-base transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/35 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 sm:h-9 md:text-sm dark:bg-input/30",
        className,
      )}
      {...props}
    />
  );
}

export { NativeSelect };
