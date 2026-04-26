import crypto from "crypto";
import { config } from "./config";

export interface WebhookPayload {
  meetingId: string;
  eventType: string;
  clientReferenceId?: string;
}

export function verifySignature(payload: string, signature: string | undefined): boolean {
  if (!config.webhookSecret) {
    console.warn("WEBHOOK_SECRET not set — skipping signature verification");
    return true;
  }

  if (!signature) {
    return false;
  }

  const expected = crypto
    .createHmac("sha256", config.webhookSecret)
    .update(payload)
    .digest("hex");

  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expected),
  );
}

export function parseWebhookPayload(body: unknown): WebhookPayload | null {
  if (
    typeof body === "object" &&
    body !== null &&
    "meetingId" in body &&
    "eventType" in body
  ) {
    return body as WebhookPayload;
  }
  return null;
}
