import fs from "fs";
import path from "path";
import { config } from "./config";
import { Transcript } from "./fireflies";

function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\-\s]/g, "").replace(/\s+/g, "_");
}

function buildFilename(transcript: Transcript): string {
  const date = new Date(transcript.date).toISOString().split("T")[0];
  const title = sanitizeFilename(transcript.title);
  return `${date}_${title}_${transcript.id}`;
}

function formatAsText(transcript: Transcript): string {
  const lines: string[] = [];

  lines.push(`Title: ${transcript.title}`);
  lines.push(`Date: ${new Date(transcript.date).toLocaleString()}`);
  lines.push(`Duration: ${formatTimestamp(transcript.duration)}`);
  lines.push(`Participants: ${transcript.participants.join(", ")}`);
  lines.push("");

  if (transcript.summary?.keywords?.length) {
    lines.push(`Keywords: ${transcript.summary.keywords.join(", ")}`);
  }
  if (transcript.summary?.action_items?.length) {
    lines.push("");
    lines.push("Action Items:");
    for (const item of transcript.summary.action_items) {
      lines.push(`  - ${item}`);
    }
  }

  lines.push("");
  lines.push("=".repeat(60));
  lines.push("TRANSCRIPT");
  lines.push("=".repeat(60));
  lines.push("");

  for (const sentence of transcript.sentences) {
    const time = formatTimestamp(sentence.start_time);
    lines.push(`[${time}] ${sentence.speaker_name}: ${sentence.text}`);
  }

  return lines.join("\n");
}

export async function saveTranscript(transcript: Transcript): Promise<{ txtPath: string; jsonPath: string }> {
  await fs.promises.mkdir(config.transcriptDir, { recursive: true });

  const basename = buildFilename(transcript);
  const txtPath = path.join(config.transcriptDir, `${basename}.txt`);
  const jsonPath = path.join(config.transcriptDir, `${basename}.json`);

  const txtContent = formatAsText(transcript);
  const jsonContent = JSON.stringify(transcript, null, 2);

  await Promise.all([
    fs.promises.writeFile(txtPath, txtContent, "utf-8"),
    fs.promises.writeFile(jsonPath, jsonContent, "utf-8"),
  ]);

  return { txtPath, jsonPath };
}
