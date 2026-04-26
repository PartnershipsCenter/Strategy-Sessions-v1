import express from "express";
import { config, validateConfig } from "./config";
import { getTranscript } from "./fireflies";
import { saveTranscript } from "./formatter";
import { verifySignature, parseWebhookPayload } from "./webhook";

validateConfig();

const app = express();

// Parse JSON but also keep raw body for signature verification
app.use(
  express.json({
    verify: (req: express.Request, _res, buf) => {
      (req as any).rawBody = buf.toString();
    },
  }),
);

app.post("/webhook", async (req, res) => {
  const rawBody = (req as any).rawBody as string;
  const signature = req.headers["x-hub-signature"] as string | undefined;

  if (!verifySignature(rawBody, signature)) {
    console.error("Webhook signature verification failed");
    res.status(401).json({ error: "Invalid signature" });
    return;
  }

  const payload = parseWebhookPayload(req.body);
  if (!payload) {
    console.error("Invalid webhook payload:", req.body);
    res.status(400).json({ error: "Invalid payload" });
    return;
  }

  if (payload.eventType !== "Transcription completed") {
    console.log(`Ignoring event: ${payload.eventType}`);
    res.status(200).json({ status: "ignored" });
    return;
  }

  console.log(`Transcription completed for meeting: ${payload.meetingId}`);

  // Respond immediately so Fireflies doesn't retry
  res.status(200).json({ status: "processing" });

  try {
    const transcript = await getTranscript(payload.meetingId);
    const { txtPath, jsonPath } = await saveTranscript(transcript);
    console.log(`Saved transcript: ${transcript.title}`);
    console.log(`  TXT: ${txtPath}`);
    console.log(`  JSON: ${jsonPath}`);
  } catch (err) {
    console.error(`Failed to fetch/save transcript ${payload.meetingId}:`, err);
  }
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", transcriptDir: config.transcriptDir });
});

app.listen(config.port, () => {
  console.log(`Fireflies webhook server listening on port ${config.port}`);
  console.log(`Transcripts will be saved to: ${config.transcriptDir}`);
  console.log(`Webhook endpoint: POST http://localhost:${config.port}/webhook`);
});
