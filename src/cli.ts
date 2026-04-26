import fs from "fs";
import { config, validateConfig } from "./config";
import { getTranscript, listAllTranscripts } from "./fireflies";
import { saveTranscript } from "./formatter";

function getDownloadedIds(): Set<string> {
  const ids = new Set<string>();
  try {
    const files = fs.readdirSync(config.transcriptDir);
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      // Filename format: YYYY-MM-DD_Title_TRANSCRIPTID.json
      const match = file.match(/([A-Z0-9]{26})\.json$/);
      if (match) {
        ids.add(match[1]);
      }
    }
  } catch {
    // Directory doesn't exist yet — no downloads
  }
  return ids;
}

async function pullSingle(id: string): Promise<void> {
  console.log(`Fetching transcript: ${id}`);
  const transcript = await getTranscript(id);
  const { txtPath, jsonPath } = await saveTranscript(transcript);
  console.log(`Saved: ${transcript.title}`);
  console.log(`  TXT: ${txtPath}`);
  console.log(`  JSON: ${jsonPath}`);
}

async function sync(): Promise<void> {
  console.log("Syncing all transcripts from Fireflies...\n");

  const existing = getDownloadedIds();
  console.log(`Found ${existing.size} transcripts already on disk.\n`);

  const all = await listAllTranscripts();
  console.log(`\nFound ${all.length} total transcripts on Fireflies.\n`);

  const toDownload = all.filter((t) => !existing.has(t.id));

  if (toDownload.length === 0) {
    console.log("Everything is up to date — no new transcripts to download.");
    return;
  }

  console.log(`Downloading ${toDownload.length} new transcripts (skipping ${all.length - toDownload.length} already on disk)...\n`);

  let success = 0;
  let failed = 0;

  for (const item of toDownload) {
    try {
      await pullSingle(item.id);
      success++;
      console.log("");
    } catch (err: any) {
      failed++;
      const msg = err?.message || String(err);
      if (msg.includes("too_many_requests") || msg.includes("Too many requests")) {
        console.error(`\nRate limited after ${success} downloads. ${toDownload.length - success - failed} transcripts remaining.`);
        console.error("Run 'npm run pull -- sync' again after the rate limit resets.\n");
        break;
      }
      console.error(`Failed to fetch ${item.id} (${item.title}): ${msg}\n`);
    }
  }

  console.log(`Done. Downloaded: ${success}, Failed: ${failed}, Already on disk: ${existing.size}`);
}

async function main(): Promise<void> {
  validateConfig();

  const args = process.argv.slice(2);
  const command = args[0];

  if (command === "get" && args[1]) {
    await pullSingle(args[1]);
  } else if (command === "sync") {
    await sync();
  } else {
    console.log("Fireflies Transcript Puller\n");
    console.log("Usage:");
    console.log("  npm run pull -- get <transcript_id>   Pull a specific transcript");
    console.log("  npm run pull -- sync                  Pull all missing transcripts (skips existing)");
  }
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
