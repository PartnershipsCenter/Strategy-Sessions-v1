import dotenv from "dotenv";
import path from "path";
import os from "os";

dotenv.config();

function resolveHome(filepath: string): string {
  if (filepath.startsWith("~/")) {
    return path.join(os.homedir(), filepath.slice(2));
  }
  return filepath;
}

export const config = {
  firefliesApiKey: process.env.FIREFLIES_API_KEY || "",
  webhookSecret: process.env.WEBHOOK_SECRET || "",
  port: parseInt(process.env.PORT || "3000", 10),
  transcriptDir: resolveHome(process.env.TRANSCRIPT_DIR || "~/Documents/transcripts"),
  graphqlEndpoint: "https://api.fireflies.ai/graphql",
};

export function validateConfig(): void {
  if (!config.firefliesApiKey) {
    throw new Error("FIREFLIES_API_KEY is required. Set it in your .env file.");
  }
}
