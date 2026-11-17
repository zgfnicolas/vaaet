import { z } from "zod";

export const env = z
  .object({
    NEXT_PUBLIC_API_URL: z.string().url(),
    NEXT_PUBLIC_API_SECRET: z.string(),
  })
  .parse(process.env);

console.log("loaded env", process.env);
